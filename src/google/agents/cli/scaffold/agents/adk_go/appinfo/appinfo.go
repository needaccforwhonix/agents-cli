// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Package appinfo adds a GET {path_prefix}/apps/{app_name}/app-info endpoint to
// the ADK Go web server, mirroring ADK Python's experimental AppInfo endpoint.
// ADK Go does not expose this route yet, so it is served here from template code
// via a custom web.Sublauncher. It lets `agents-cli eval` introspect a running
// agent (name, description, per-agent instruction and tool declarations) over
// HTTP, the same way it can for Python agents.
package appinfo

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"reflect"
	"strings"

	"github.com/gorilla/mux"
	"google.golang.org/genai"

	adkagent "google.golang.org/adk/v2/agent"
	"google.golang.org/adk/v2/cmd/launcher"
	weblauncher "google.golang.org/adk/v2/cmd/launcher/web"
	"google.golang.org/adk/v2/session"
	"google.golang.org/adk/v2/tool"
)

// AppInfo mirrors adk-python's AppInfo
// https://github.com/google/adk-python/blob/main/src/google/adk/cli/api_server.py
type AppInfo struct {
	Name          string               `json:"name"`
	RootAgentName string               `json:"rootAgentName"`
	Description   string               `json:"description"`
	Language      string               `json:"language"`
	IsComputerUse bool                 `json:"isComputerUse"`
	Agents        map[string]AgentInfo `json:"agents"`
}

// AgentInfo mirrors adk-python's AgentInfo
// https://github.com/google/adk-python/blob/main/src/google/adk/utils/agent_info.py
type AgentInfo struct {
	Name        string        `json:"name"`
	Description string        `json:"description"`
	Instruction string        `json:"instruction"`
	Tools       []*genai.Tool `json:"tools"`
	SubAgents   []string      `json:"subAgents"`
}

// declarer is the exported-method view of a tool that can describe itself.
// tool.Tool does not expose Declaration(), but the concrete tools returned ex. by
// functiontool.New implement Declaration() method.
type declarer interface {
	Declaration() *genai.FunctionDeclaration
}

// metadataContext is a read-only agent context used only to enumerate a
// toolset's tools for app-info. This suffices for toolsets that list tools
// without inspecting session state (e.g. MCP).
type metadataContext struct {
	context.Context
}

var _ adkagent.ReadonlyContext = metadataContext{}

func (metadataContext) UserContent() *genai.Content          { return nil }
func (metadataContext) InvocationID() string                 { return "" }
func (metadataContext) AgentName() string                    { return "" }
func (metadataContext) ReadonlyState() session.ReadonlyState { return nil }
func (metadataContext) UserID() string                       { return "" }
func (metadataContext) AppName() string                      { return "" }
func (metadataContext) SessionID() string                    { return "" }
func (metadataContext) Branch() string                       { return "" }

// toolDeclarations converts an agent's static tools and toolsets into the genai
// tool declarations reported by app-info. Mirrors adk-python's get_tools_info
// (https://github.com/google/adk-python/blob/main/src/google/adk/utils/agent_info.py):
// tools without a declaration are omitted.
func toolDeclarations(tools []tool.Tool, toolsets []tool.Toolset) []*genai.Tool {
	all := append([]tool.Tool(nil), tools...)
	for _, ts := range toolsets {
		expanded, err := ts.Tools(metadataContext{Context: context.Background()})
		if err != nil {
			log.Printf("appinfo: skipping toolset %q: %v", ts.Name(), err)
			continue
		}
		all = append(all, expanded...)
	}

	out := make([]*genai.Tool, 0, len(all))
	for _, t := range all {
		if d, ok := t.(declarer); ok {
			out = append(out, &genai.Tool{
				FunctionDeclarations: []*genai.FunctionDeclaration{d.Declaration()},
			})
		}
	}
	return out
}

// llmAgentPkgPath is the import path of ADK Go's LlmAgent implementation for reflaction.
const llmAgentPkgPath = "google.golang.org/adk/v2/agent/llmagent"

// llmAgentState holds the parts of an LlmAgent that ADK Go does not expose on the
// public agent.Agent interface but are read via reflection instead.
type llmAgentState struct {
	instruction string
	tools       []tool.Tool
	toolsets    []tool.Toolset
}

// reflectLLMAgent reports whether a is an ADK Go LlmAgent and, if so, extracts
// its instruction, tools and toolsets.
func reflectLLMAgent(a adkagent.Agent) (llmAgentState, bool) {
	rt := reflect.TypeOf(a)
	if rt == nil || rt.Kind() != reflect.Pointer || rt.Elem().PkgPath() != llmAgentPkgPath {
		return llmAgentState{}, false // not an LlmAgent
	}

	state := reflect.ValueOf(a).Elem().FieldByName("State")
	if !state.IsValid() || state.Kind() != reflect.Struct {
		log.Printf("appinfo: LlmAgent %q has no embedded State "+
			"reporting it without instruction or tools", a.Name())
		return llmAgentState{}, true
	}

	instruction, _ := fieldValue[string](state, "Instruction")
	tools, toolsOK := fieldValue[[]tool.Tool](state, "Tools")
	toolsets, _ := fieldValue[[]tool.Toolset](state, "Toolsets")
	if !toolsOK {
		log.Printf("appinfo: could not read tools of LlmAgent %q via reflection "+
			"reporting it without tools", a.Name())
	}
	return llmAgentState{instruction: instruction, tools: tools, toolsets: toolsets}, true
}

// fieldValue reads exported struct field name from v and type-asserts it to T,
// returning the zero value and false if the field is absent or not a T.
func fieldValue[T any](v reflect.Value, name string) (T, bool) {
	var zero T
	f := v.FieldByName(name)
	// CanInterface guards against panicking on unexported fields.
	if !f.IsValid() || !f.CanInterface() {
		return zero, false
	}
	t, ok := f.Interface().(T)
	return t, ok
}

// BuildAppInfo walks the agent tree rooted at the app loaded by name and
// assembles the AppInfo payload.
//
// It reports and recurses into LlmAgents only.
func BuildAppInfo(loader adkagent.Loader, appName string) (*AppInfo, error) {
	root, err := loader.LoadAgent(appName)
	if err != nil {
		return nil, err
	}

	agents := map[string]AgentInfo{}
	// walk records a in agents if it is an LlmAgent and reports whether it is
	// one, so a parent can list only its LlmAgent children in subAgents.
	var walk func(a adkagent.Agent) bool
	walk = func(a adkagent.Agent) bool {
		st, isLLM := reflectLLMAgent(a)
		if !isLLM {
			return false
		}
		if _, seen := agents[a.Name()]; seen {
			return true
		}

		subNames := make([]string, 0, len(a.SubAgents()))
		for _, sub := range a.SubAgents() {
			if walk(sub) {
				subNames = append(subNames, sub.Name())
			}
		}

		agents[a.Name()] = AgentInfo{
			Name:        a.Name(),
			Description: a.Description(),
			Instruction: st.instruction,
			Tools:       toolDeclarations(st.tools, st.toolsets),
			SubAgents:   subNames,
		}
		return true
	}
	walk(root)

	return &AppInfo{
		Name:          appName,
		RootAgentName: root.Name(),
		Description:   root.Description(),
		Language:      "go",
		Agents:        agents,
	}, nil
}

// defaultPathPrefix is the prefix of the appInfo route, unless overriden by the
// `-path_prefix` flag. It defaults to "/" (the root) so callers can mount
// app-info at the root without passing the flag; normalizePathPrefix maps "/" to
// an empty prefix.
const defaultPathPrefix = "/"

// appInfoSuffix is the route appended after the path prefix to form the endpoint path.
const appInfoSuffix = "/apps/{app_name}/app-info"

// normalizePathPrefix canonicalizes a -path_prefix value into a leading-slash,
// no-trailing-slash prefix, mapping "/" (and "") to "" so the route is served at
// the root.
func normalizePathPrefix(prefix string) string {
	trimmed := strings.Trim(prefix, "/")
	if trimmed == "" {
		return ""
	}
	return "/" + trimmed
}

// launcher is a web.Sublauncher that serves the app-info route.
type appInfoLauncher struct {
	flags      *flag.FlagSet
	pathPrefix *string
}

// NewLauncher creates the app-info sublauncher, activated by the "appinfo"
// keyword. Register it before the "api" sublauncher: the api sublauncher claims
// its whole prefix with a catch-all, so this more specific route must be
// registered first to win.
func NewLauncher() weblauncher.Sublauncher {
	flags := flag.NewFlagSet("appinfo", flag.ContinueOnError)
	return &appInfoLauncher{
		flags: flags,
		pathPrefix: flags.String(
			"path_prefix",
			defaultPathPrefix,
			`URL prefix to mount app-info under; "/" serves it at the root`,
		),
	}
}

func (a *appInfoLauncher) Keyword() string { return "appinfo" }

func (a *appInfoLauncher) SimpleDescription() string {
	return "serves GET {path_prefix}/apps/{app_name}/app-info (agent metadata for eval)"
}

func (a *appInfoLauncher) CommandLineSyntax() string {
	return `  appinfo [-path_prefix <prefix>]  (prefix defaults to "/", serving at the root)`
}

// route is the fully-resolved endpoint path; only valid after Parse.
func (a *appInfoLauncher) route() string {
	return normalizePathPrefix(*a.pathPrefix) + appInfoSuffix
}

func (a *appInfoLauncher) Parse(args []string) ([]string, error) {
	if err := a.flags.Parse(args); err != nil {
		return nil, err
	}
	return a.flags.Args(), nil
}

func (a *appInfoLauncher) UserMessage(webURL string, printer func(v ...any)) {
	printer(fmt.Sprintf("       appinfo:  GET %s%s", webURL, a.route()))
}

func (a *appInfoLauncher) SetupSubrouters(router *mux.Router, config *launcher.Config) error {
	router.Methods("GET").Path(a.route()).HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			appName := mux.Vars(r)["app_name"]
			info, err := BuildAppInfo(config.AgentLoader, appName)
			if err != nil {
				http.Error(w, err.Error(), http.StatusNotFound)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			if err := json.NewEncoder(w).Encode(info); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
			}
		})
	return nil
}

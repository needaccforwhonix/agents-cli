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

package appinfo

import (
	"testing"

	"google.golang.org/adk/v2/agent"
	"google.golang.org/adk/v2/agent/llmagent"
	"google.golang.org/adk/v2/tool"
	"google.golang.org/adk/v2/tool/functiontool"
)

type echoArgs struct {
	Text string `json:"text" jsonschema:"the text to echo"`
}

type echoResult struct {
	Text string `json:"text"`
}

func echo(_ agent.Context, a echoArgs) (echoResult, error) {
	return echoResult{Text: a.Text}, nil
}

func newEchoTool(t *testing.T) tool.Tool {
	t.Helper()
	tl, err := functiontool.New(functiontool.Config{Name: "echo", Description: "echo the input"}, echo)
	if err != nil {
		t.Fatalf("functiontool.New: %v", err)
	}
	return tl
}

// TestReflectLLMAgentExtractsMetadata guards the reflection-based extraction that
// app-info depends on. If it fails, ADK Go's internal llmagent State layout has
// changed.
func TestReflectLLMAgentExtractsMetadata(t *testing.T) {
	llm, err := llmagent.New(llmagent.Config{
		Name:        "root",
		Instruction: "be helpful",
		Tools:       []tool.Tool{newEchoTool(t)},
	})
	if err != nil {
		t.Fatalf("llmagent.New: %v", err)
	}

	st, ok := reflectLLMAgent(llm)
	if !ok {
		t.Fatal("reflectLLMAgent returned ok=false for an LlmAgent; ADK Go internals may have changed")
	}
	if st.instruction != "be helpful" {
		t.Errorf("instruction = %q, want %q", st.instruction, "be helpful")
	}
	if len(st.tools) != 1 {
		t.Fatalf("tools len = %d, want 1", len(st.tools))
	}
	if st.tools[0].Name() != "echo" {
		t.Errorf("tool name = %q, want %q", st.tools[0].Name(), "echo")
	}
}

func TestReflectLLMAgentRejectsNonLLM(t *testing.T) {
	base, err := agent.New(agent.Config{Name: "custom"})
	if err != nil {
		t.Fatalf("agent.New: %v", err)
	}
	if _, ok := reflectLLMAgent(base); ok {
		t.Error("reflectLLMAgent returned ok=true for a non-LlmAgent")
	}
}

func TestBuildAppInfoReportsLLMAgentsOnly(t *testing.T) {
	child, err := llmagent.New(llmagent.Config{
		Name:        "child",
		Instruction: "child instruction",
		Tools:       []tool.Tool{newEchoTool(t)},
	})
	if err != nil {
		t.Fatalf("llmagent.New child: %v", err)
	}
	custom, err := agent.New(agent.Config{Name: "custom"})
	if err != nil {
		t.Fatalf("agent.New custom: %v", err)
	}
	root, err := llmagent.New(llmagent.Config{
		Name:        "root",
		Instruction: "root instruction",
		Tools:       []tool.Tool{newEchoTool(t)},
		SubAgents:   []agent.Agent{child, custom},
	})
	if err != nil {
		t.Fatalf("llmagent.New root: %v", err)
	}

	info, err := BuildAppInfo(agent.NewSingleLoader(root), "root")
	if err != nil {
		t.Fatalf("BuildAppInfo: %v", err)
	}

	if info.RootAgentName != "root" {
		t.Errorf("RootAgentName = %q, want %q", info.RootAgentName, "root")
	}
	if _, ok := info.Agents["custom"]; ok {
		t.Error(`non-LlmAgent "custom" should not be reported`)
	}

	rootInfo, ok := info.Agents["root"]
	if !ok {
		t.Fatal("root agent missing from app-info")
	}
	if got := rootInfo.SubAgents; len(got) != 1 || got[0] != "child" {
		t.Errorf("root.SubAgents = %v, want [child]", got)
	}

	childInfo, ok := info.Agents["child"]
	if !ok {
		t.Fatal("child agent missing from app-info")
	}
	if childInfo.Instruction != "child instruction" {
		t.Errorf("child.Instruction = %q, want %q", childInfo.Instruction, "child instruction")
	}
	if len(childInfo.Tools) != 1 {
		t.Errorf("child.Tools len = %d, want 1", len(childInfo.Tools))
	}
}

func TestNormalizePathPrefix(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want string
	}{
		{"root maps to empty", "/", ""},
		{"empty maps to empty", "", ""},
		{"bare word gets a leading slash", "api", "/api"},
		{"trailing slash trimmed", "/api/", "/api"},
		{"nested prefix preserved", "/foo/bar/", "/foo/bar"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := normalizePathPrefix(tt.in); got != tt.want {
				t.Errorf("normalizePathPrefix(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}

func TestLauncherRoute(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want string
	}{
		{"default serves at the root", nil, appInfoSuffix},
		{"explicit root serves at the root", []string{"-path_prefix", "/"}, appInfoSuffix},
		{"custom prefix is prepended", []string{"-path_prefix", "/api"}, "/api" + appInfoSuffix},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			l, ok := NewLauncher().(*appInfoLauncher)
			if !ok {
				t.Fatalf("NewLauncher() is not *appInfoLauncher")
			}
			if _, err := l.Parse(tt.args); err != nil {
				t.Fatalf("Parse(%v): %v", tt.args, err)
			}
			if got := l.route(); got != tt.want {
				t.Errorf("route() = %q, want %q", got, tt.want)
			}
		})
	}
}

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Build stage
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app

# Copy pom.xml first for dependency caching
COPY pom.xml ./
RUN mvn dependency:go-offline -B

# Copy source and build
COPY src ./src
RUN mvn package -DskipTests -B

# Runtime stage
FROM eclipse-temurin:17-jre

WORKDIR /app

# Copy the shaded JAR from builder
COPY --from=builder /app/target/app.jar app.jar

ARG COMMIT_SHA=""
ENV COMMIT_SHA=${COMMIT_SHA}

{%- if cookiecutter.agent_gateway %}

# Install the Agent Gateway root CA passed by the platform.
# Based on https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-gateway-runtime-deploy#configure-byoc
ARG AGENT_GATEWAY_ROOT_CERTIFICATES
RUN if [ -n "$AGENT_GATEWAY_ROOT_CERTIFICATES" ]; then \
      mkdir -p /usr/local/share/ca-certificates; \
      printf "%b" "$AGENT_GATEWAY_ROOT_CERTIFICATES" \
        | awk 'BEGIN {c=0} /BEGIN CERTIFICATE/ {c++} c > 0 { print > "/usr/local/share/ca-certificates/agw-" c ".crt" }'; \
      update-ca-certificates; \
      for crt in /usr/local/share/ca-certificates/agw-*.crt; do \
        [ -e "$crt" ] || continue; \
        keytool -importcert -noprompt -trustcacerts \
          -alias "agent-gateway-$(basename "$crt" .crt)" \
          -file "$crt" \
          -keystore "$JAVA_HOME/lib/security/cacerts" \
          -storepass changeit; \
      done; \
    fi

# If Agent Gateway root CA was provided, configure SSL/TLS trust paths.
ENV SSL_CERT_FILE=${AGENT_GATEWAY_ROOT_CERTIFICATES:+/etc/ssl/certs/ca-certificates.crt}
{%- endif %}

EXPOSE 8080

# Cloud Run sets PORT env var
# ADK web server supports API and Web UI
ENTRYPOINT ["java", "-jar", "app.jar"]

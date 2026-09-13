# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load test against the A2A route this project serves.

Replaces the deployment target's copy, which posts to routes only an ADK
server has, after creating a session through its session API.
"""

import logging
import os
import time
import uuid

from locust import HttpUser, between, task

ENDPOINT = "/a2a/app/"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ChatStreamUser(HttpUser):
    """Sends A2A JSON-RPC messages the way a client would."""

    wait_time = between(1, 3)

    @task
    def chat_stream(self) -> None:
        headers = {"Content-Type": "application/json"}
        if os.environ.get("_ID_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['_ID_TOKEN']}"

        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/stream",
            "params": {
                "message": {
                    "messageId": f"msg-{uuid.uuid4()}",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello! Weather in New York?"}],
                }
            },
        }

        start_time = time.time()
        with self.client.post(
            ENDPOINT,
            name=f"{ENDPOINT} message/stream",
            headers=headers,
            json=request,
            catch_response=True,
            stream=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Got status code {response.status_code}")
                return
            # Streaming: the run is only useful once bytes actually arrive.
            received = False
            for chunk in response.iter_lines():
                if chunk:
                    received = True
                    break
            if received:
                response.success()
                logger.info(f"First chunk in {time.time() - start_time:.2f}s")
            else:
                response.failure("Stream closed without a chunk")

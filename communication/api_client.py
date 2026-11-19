from typing import Optional

import requests


class ApiError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def post_json(
        self,
        path: str,
        payload: dict,
        device_token: Optional[str] = None,
    ) -> requests.Response:
        url = self.base_url + path.lstrip("/")
        headers = {"Content-Type": "application/json"}
        if device_token:
            headers["x-device-token"] = device_token

        try:
            return requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise ApiError(
                f"Backend did not respond within {self.timeout_seconds:g} seconds"
            ) from exc
        except requests.ConnectionError as exc:
            raise ApiError(f"Could not connect to backend: {exc}") from exc
        except requests.RequestException as exc:
            raise ApiError(f"HTTP request failed: {exc}") from exc

    def post_multipart(
        self,
        path: str,
        fields: dict,
        file_field: str,
        filename: str,
        file_bytes: bytes,
        content_type: str,
        device_token: str,
    ) -> requests.Response:
        url = self.base_url + path.lstrip("/")
        headers = {"x-device-token": device_token}
        try:
            return requests.post(
                url,
                data=fields,
                files={
                    file_field: (filename, file_bytes, content_type),
                },
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise ApiError(
                f"Backend did not respond within {self.timeout_seconds:g} seconds"
            ) from exc
        except requests.ConnectionError as exc:
            raise ApiError(f"Could not connect to backend: {exc}") from exc
        except requests.RequestException as exc:
            raise ApiError(f"HTTP request failed: {exc}") from exc

    @staticmethod
    def response_summary(response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text.strip()
        if isinstance(body, dict) or isinstance(body, list):
            return str(body)
        return str(body)[:200] if body else "No response body"

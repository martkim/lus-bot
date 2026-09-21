"""HTML이 참조하는 CSS/JS URL에 내용 기반 버전을 붙여 캐시를 무효화한다.

왜 필요한가 (2026-09-22 실측):
HTML은 Cache-Control: no-cache라 매번 새로 내려가지만, CSS/JS는 오리진이
max-age=300을 줘도 Cloudflare가 브라우저 캐시를 max-age=14400(4시간)으로 덮어쓴다.
그래서 CSS를 고쳐 배포해도 이미 접속했던 기기에서는 최대 4시간 동안 예전 파일이
그대로 쓰였다. 실제로 토스트 가독성 수정이 반영되지 않는다는 제보가 여기서 나왔다.

해결 방식:
파일이 바뀌면 URL 자체가 바뀌게 한다(/style.css -> /style.css?v=a1b2c3d4).
URL이 다르면 브라우저도 CDN도 새로 받을 수밖에 없으므로, 캐시 설정과 무관하게
배포 즉시 반영된다. 항상 최신인 HTML이 새 URL을 실어 나르는 구조다.
"""

import hashlib
import os
import re
from typing import Dict, Tuple

LOG_TAG = "[AssetVersionService]"

# 로컬 루트 상대 경로의 css/js만 대상으로 한다.
# 이미 쿼리가 붙은 것과 https:// 로 시작하는 외부 CDN은 건드리지 않는다.
_ASSET_REF = re.compile(r'(?P<attr>href|src)="(?P<path>/[^"?#]+\.(?:css|js))"')


class AssetVersionService:
    """public 디렉터리의 에셋 지문을 계산하고 HTML에 주입한다."""

    def __init__(self, public_dir: str) -> None:
        self._public_dir = public_dir
        # url_path -> (mtime_ns, size, digest) — 파일이 그대로면 다시 해시하지 않는다
        self._fingerprints: Dict[str, Tuple[int, int, str]] = {}
        # html 파일명 -> (mtime_ns, 원본 본문). 치환 결과가 아니라 원본을 캐시한다.
        # 치환본을 캐시하면 HTML이 그대로고 CSS만 바뀐 경우를 놓친다.
        self._sources: Dict[str, Tuple[int, str]] = {}

    def _local_path(self, url_path: str) -> str:
        return os.path.join(self._public_dir, url_path.lstrip("/").replace("/", os.sep))

    def fingerprint(self, url_path: str) -> str:
        """에셋 내용의 짧은 해시. 파일이 없으면 빈 문자열."""
        path = self._local_path(url_path)
        try:
            stat = os.stat(path)
        except OSError:
            return ""

        cached = self._fingerprints.get(url_path)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return cached[2]

        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:10]
        self._fingerprints[url_path] = (stat.st_mtime_ns, stat.st_size, digest)
        return digest

    def render(self, html_filename: str) -> str:
        """HTML을 읽어 에셋 참조에 ?v=<지문>을 붙인 본문을 돌려준다.

        원본은 파일이 바뀔 때만 다시 읽고, 치환은 매 요청 수행한다.
        지문 계산 자체가 mtime/size로 캐시돼 있어 비용은 stat 몇 번뿐이다."""
        html_path = os.path.join(self._public_dir, html_filename)
        stat = os.stat(html_path)

        cached = self._sources.get(html_filename)
        if cached and cached[0] == stat.st_mtime_ns:
            source = cached[1]
        else:
            with open(html_path, "r", encoding="utf-8") as handle:
                source = handle.read()
            self._sources[html_filename] = (stat.st_mtime_ns, source)

        return self._inject(source)

    def _inject(self, body: str) -> str:
        def repl(match: "re.Match[str]") -> str:
            url_path = match.group("path")
            digest = self.fingerprint(url_path)
            if not digest:
                return match.group(0)
            return f'{match.group("attr")}="{url_path}?v={digest}"'

        return _ASSET_REF.sub(repl, body)

# alles

> 2026년 7월 21일 검토 완료 · 기준 원문: `README.md` · 원문 리비전:
> `phase10-canonical-2026-07-21`

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · **한국어** ·
[العربية](README.ar.md)

**alles**는 직접 호스팅하는 개인용 앱입니다. 하나의 Python 프로그램에 Aide, 검색, 이메일,
서로 연결된 Markdown 문서, 저널, 파일, 캘린더, 할 일, 재정, 사진, 연락처, 암호화 보관함이
들어 있습니다. 로컬 데이터는 사용자가 관리하는 폴더에 남습니다. 원격 측정은 없으며 외부
제공자는 사용자가 직접 보내기로 선택한 요청만 받습니다.

## 빠른 시작

Python 3.11 이상이 필요합니다.

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

`http://localhost:6769`을 여세요. 시작할 때 API 키는 필요하지 않습니다. Aide를 사용할 때만
**설정 → 모델**에서 모델을 추가하세요.

macOS/Linux 관리형 설치는 `./alles install`을 실행합니다. `alles update`는 새 릴리스를 준비하고
상태를 확인하며, `alles update rollback`은 연결된 이전 코드와 데이터를 복원합니다.
`./alles uninstall`은 개인 데이터를 보존합니다.

Docker:

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

루프백 주소에만 바인딩하므로 새 컨테이너는 이 장치에서만 접근할 수 있습니다.

## 데이터, 네트워크, 백업

Alles는 한 사람을 위해 설계되었습니다. 네트워크 접근을 허용하기 전에 인증을 켜고 강력한 소유자
비밀번호와 실제 `secret_key`를 설정하세요. 공개하기 전에
[보안 안내](../../specifications.md#security--read-before-exposing-it)를 읽으세요.

**설정 → 백업**에서 암호화된 로컬 백업을 만들거나 WebDAV 또는 S3 호환 저장소로 수동 전송할
수 있습니다. 복구 키는 별도로 보관하세요. 복원 자료는 현재 데이터에 적용하기 전에 검증되고
스테이징됩니다.

## 자세히 보기

앱, 경로, 아키텍처 전체 목록은 [`specifications.md`](../../specifications.md)에 있습니다.
종속성과 라이선스는 [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md)에 정리됩니다.

## 라이선스

MIT. [`LICENSE`](../../LICENSE)를 확인하세요.

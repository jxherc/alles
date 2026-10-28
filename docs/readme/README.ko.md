# alles

> 2026년 10월 27일 검토 완료 · 기준 원문: `README.md` · 원문 리비전:
> `davinci-canonical-2026-10-27`

alles는 Google 생태계를 대신하는 프라이빗한 대안입니다. 메일, 캘린더, 문서, 파일, 사진, 연락처, 할 일, 돈 관리, 비밀번호를 남의 서버가 아니라 내가 관리하는 기기의 앱 하나에 모아 둡니다.

한 사람이 쓰도록 만들었습니다. 주요 데이터는 내가 관리하는 폴더에 저장되고, 어떤 외부 서비스를 연결할지도 직접 정합니다. AI 어시스턴트 aide도 들어 있어서, 작업을 승인하면 앱 안에서 일을 처리해 줍니다. 도움이 되면 쓰세요. 로컬 도구는 AI 모델 없이도 작동합니다.

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · **한국어** ·
[العربية](README.ar.md)

## 시작하기

macOS나 Linux에서 다음을 실행하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

앱만 내려받아 백그라운드 서비스로 설정하고, 진행되는 단계를 하나씩 보여 줍니다. 터미널을 닫아도 alles는 계속 실행되고, 컴퓨터를 다시 시작해도 자동으로 켜집니다. Python 3.11 이상이 필요합니다. Debian이나 Ubuntu에서 Python venv 모듈이 없으면 설치 프로그램이 설치를 제안합니다.

그다음 [http://localhost:6769](http://localhost:6769)을 열고 설정을 따라가세요. 시작하는 데 API 키는 필요 없습니다. 이후에는 `alles` 명령 하나로 충분합니다. 그냥 실행하면 alles가 실행 중인지와 여는 방법을 보여 주고, `alles doctor`는 설치를 점검하며, `alles config`는 설정 파일을 엽니다.

기본적으로 alles는 이 기기에서만 접근할 수 있고 비밀번호 없이 시작합니다. **네트워크에 올리기 전에** 비밀번호를 정하고 누가 열 수 있는지 고르세요. `alles access lan`이 둘 다 해 줍니다. 로컬 네트워크 접근과 공개 접근은 요구 사항이 다르니 먼저 [보안](../../specifications.md#security--read-before-exposing-it) 내용을 읽어 보세요. 설치 직후에 비밀번호를 설정할지(8자 이상, 나중에 `alles password`로 설정하거나 바꿀 수 있어요), 다른 기기에서도 열 수 있게 할지 물어봐요.

### 다른 기기에서 사용하기

```bash
alles access lan
```

소유자 비밀번호를 묻고, 휴대폰과 다른 컴퓨터에서 열 수 있도록 alles를 다시 시작한 뒤, 사용할 주소(예: `http://100.101.102.103:6769`)를 보여 줍니다. `alles access device`를 실행하면 다시 이 컴퓨터에서만 쓸 수 있습니다.

### 소스에서 실행하기

개발용이거나 서비스 없이 실행하고 싶을 때 쓰세요. Debian이나 Ubuntu에서는 먼저 `sudo apt install git python3-venv`를 실행하세요.

```bash
git clone https://github.com/jxherc/alles.git
cd alles
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python app.py
```

여기서도 `python cli.py access lan`으로 다른 기기의 접근을 설정할 수 있습니다. 그런 다음 `python app.py`를 다시 실행하세요.

Docker를 쓰고 싶다면 이렇게 하세요.

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

이렇게 하면 접근이 내 기기로 제한되고 데이터는 `alles-data` 볼륨에 저장됩니다. 컨테이너를 교체할 때도 이 볼륨은 남겨 두세요.

## 할 수 있는 일

| 앱 | 용도 |
| --- | --- |
| home | 하루 일정 보기, 앱 열기, 할 일 빠르게 적기 |
| aide | 설정한 모델과 대화하고 작업 공간에서 할 작업 승인하기 |
| andromeda | 웹을 검색하고, 원하면 출처가 달린 요약 받기 |
| plan | 캘린더, 할 일, 알림, 카운트다운 관리하기 |
| inbox | 계정을 연결한 뒤 메일 읽고 연락처 관리하기 |
| docs | Markdown 노트와 일기 쓰기 |
| files | 로컬 또는 연결된 저장소, 오프라인 사본, 사진 둘러보기 |
| library | 글과 읽기 목록 저장하기 |
| health | 습관과 건강 기록 관리하기 |
| finance | 계좌, 거래, 예산, 구독 관리하기 |
| vault | 비밀 정보, 비밀번호, 패스키를 암호화해 보관하기 |
| server | 상태, 접근 설정, 백업, 업데이트 확인하기 |

로컬 재무 원장에 직접 입력해 저장한 새 거래는 실행 취소할 수 있습니다. 실행 취소는 바로 그 거래만 삭제하며, 저장된 내용이 바뀌지 않았을 때만 가능합니다. 응답이 중간에 끊기면 같은 거래를 다시 시도할 수 있습니다. Actual 거래, 가져오기, 이체는 기존의 검토 및 삭제 절차를 따릅니다.

일부 기능은 먼저 연결해야 쓸 수 있습니다. 메일을 쓰려면 IMAP/SMTP 계정을 추가하고, 온라인 저장소나 은행은 해당 서비스를 연결하세요. aide를 쓰려면 **settings → models**에서 모델을 추가하세요. Ollama로 돌리는 로컬 모델도 쓸 수 있습니다.

메일에서 gmail, outlook, icloud, yahoo, fastmail 중 하나를 고르면 양식이 알아서 채워져요. gmail은 한 번만 하는 google cloud 설정 뒤에 google로 로그인하고, alles가 단계별로 안내해요(클라이언트 json을 내려받아 끌어다 놓으면 돼요). 은행 동기화는 **finance → bank connections**에 있어요(캐나다와 미국 대부분 은행은 plaid, 또는 simplefin).

화면 언어는 english, français, español, 简体中文, 繁體中文, 日本語, 한국어, العربية 중에서 고를 수 있습니다. **설정 → 언어 및 지역**에서 바꾸세요.

앱의 자세한 동작, 아키텍처, API, 설정은 [specifications.md](../../specifications.md)에 있습니다.

## 데이터와 백업

설치한 alles는 데이터베이스와 관리하는 파일을 Linux에서는 `~/.local/share/alles/data`, macOS에서는 `~/Library/Application Support/Alles/data`에 둡니다. 위치는 `alles status`로 확인할 수 있습니다. 소스에서 실행하면 `data/`를 쓰고, `ALLES_DATA`를 설정했다면 그 위치를 씁니다. 이 폴더는 비공개로 두고 꼭 백업하세요. 외부 제공자는 각 연결을 통해 보낸 요청을 받습니다.

**settings → backup**을 열면 암호화된 백업을 내려받을 수 있습니다. 기존 HTTPS WebDAV 폴더나 S3 호환 버킷으로 직접 보낼 수도 있고, 처음 설정할 때 매일 로컬 백업을 켜 둘 수도 있습니다. 앱이 작동하지 않을 때도 꺼낼 수 있도록 복구 키는 alles 밖에 보관하세요.

alles는 백업을 확인하고 복원을 준비한 뒤에 적용합니다. 앱을 멈춘 다음 안내되는 명령을 따르세요. 기존 설치를 옮기기 전에 [백업과 복원 상세 내용](../../specifications.md#your-data-where-everything-lives)을 읽어 보세요.

## 업데이트와 제거

`alles update`는 최신 버전을 설치하고 이전 버전을 남겨 두므로, `alles update rollback`으로 데이터와 함께 이전 상태로 되돌릴 수 있습니다. `alles uninstall`은 alles를 제거하지만 개인 데이터는 남겨 둡니다. `alles help`로 모든 명령을 볼 수 있습니다.

alles는 FastAPI, SQLite, 순수 JavaScript, CSS로 만들었습니다. 프런트엔드 빌드 단계는 없습니다. 기술적인 내용은 [specifications.md](../../specifications.md)에 있습니다.

## 릴리스 기록

[davinci](../../docs/releases/davinci.md)에는 완료된 일상 작업 흐름 마일스톤이 기록되어 있습니다.

## 크레딧과 라이선스

aide는 [odysseus](https://github.com/pewdiepie-archdaemon/odysseus)에서 영감을 받았습니다. alles는 독립적으로 구현한 프로젝트입니다. [acknowledgments.md](../../ACKNOWLEDGMENTS.md)에서 그 프로젝트와 alles가 사용하는 다른 작업들의 출처를 밝힙니다. 서드파티 라이선스는 [서드파티 고지](../../THIRD_PARTY_NOTICES.md)에 있습니다.

alles는 [MIT 라이선스](../../LICENSE)로 배포됩니다.

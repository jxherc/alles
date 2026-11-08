# alles

"AH-luss"(/ˈaləs/)라고 읽어요. 독일어로 "모든 것"이라는 뜻이에요.

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

### 다른 드라이브에 설치하기

드라이브의 폴더에서 설치를 실행하면 alles가 그곳의 `Alles` 폴더에 들어갑니다:

```bash
cd /Volumes/External
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | sh
```

어디서든 폴더를 직접 정할 수도 있습니다:

```bash
curl -fsSL https://raw.githubusercontent.com/jxherc/alles/main/install.sh | ALLES_HOME=/Volumes/External/Alles sh
```

그러면 alles는 모든 것을 이 폴더에 둡니다. 문서와 파일은 보이는 곳에, 데이터베이스, 앱, 백업, 설정은 그 안의 숨김 폴더 `.alles`에 들어갑니다. 이 컴퓨터에는 `alles` 명령과 서비스를 시작하는 작은 파일만 남고, 이후의 모든 명령(`alles update` 포함)은 폴더를 알아서 찾습니다. 드라이브가 연결되어 있지 않으면 설치는 아무것도 만들기 전에 멈추고, `alles`는 드라이브가 없다고 알려 주며, 서비스는 빈 상태로 시작하지 않고 드라이브를 기다립니다. `ALLES_PORT=8000`으로 같은 방식으로 포트도 바꿀 수 있습니다.

mac에서는 처음 시작할 때 `alles-server`가 이동식 볼륨의 파일에 접근해도 되는지 묻습니다. 허용을 누르세요. 그러지 않으면 서비스가 드라이브에서 아무것도 열지 못합니다. apple의 명령어 도구(`xcode-select --install`)가 필요합니다. 나중에 설치했다면 `alles restart`를 실행하세요.

### 다른 기기에서 사용하기

```bash
alles access lan
```

소유자 비밀번호를 묻고, 휴대폰과 다른 컴퓨터에서 열 수 있도록 alles를 다시 시작한 뒤, 사용할 주소(예: `http://100.101.102.103:6769`)를 보여 줍니다. `alles access device`를 실행하면 다시 이 컴퓨터에서만 쓸 수 있습니다.

### iphone과 ipad 앱

`ios/`에는 apple의 liquid glass 스타일로 만든 iphone과 ipad용 네이티브 앱(ios 26.1 이상)이 있습니다. 홈에는 다음 일정, 마감인 할 일, 오늘의 습관이 나옵니다. aide는 평범한 채팅이고, 답장 도중에 나가면 답장이 탭 위의 작은 막대에서 계속됩니다. plan에는 오늘, 캘린더, 할 일이 있고, andromeda는 탭 막대의 검색 자리에 있으며, docs는 markdown을 읽고 편집하고, 다른 앱은 alles의 페이지로 열립니다. 먼저 `alles access lan`을 실행하고, 내 apple 개발자 팀으로 xcode에서 `ios/Alles.xcodeproj`를 연 다음, alles 주소와 소유자 비밀번호로 로그인하세요. 앱은 자기 토큰을 따로 가지므로(설정의 토큰 목록에 보입니다) alles를 다시 시작해도 로그아웃되지 않습니다.

### 내 도메인에서 열기

```bash
alles access domain alles.example.com
```

그러면 각 앱이 슬래시 뒤에 놓입니다: `alles.example.com/docs`, `alles.example.com/plan`. `subdomain`을 붙이면(`alles access domain alles.example.com subdomain`) 각 앱이 `docs.alles.example.com`처럼 자기 주소를 갖습니다. 이때는 와일드카드 DNS 레코드와 인증서가 필요합니다. 인증서는 alles가 만들지 않습니다. 도메인을 이 컴퓨터로 향하게 하고 https 프록시(caddy, nginx, cloudflare 터널)가 `http://127.0.0.1:6769`로 보내도록 하세요. `alles access domain off`로 해제합니다.

### andromeda를 브라우저 검색으로

설정 › andromeda › 기본 검색에서 chrome, brave, edge, helium용 작은 확장 프로그램을 내려받을 수 있습니다. 압축을 풀고 `chrome://extensions`를 열어 개발자 모드를 켠 뒤 폴더를 불러오면 andromeda가 기본 검색이 됩니다. 다른 브라우저는 거기 나오는 검색 주소를 사용자 지정 검색 엔진으로 쓸 수 있습니다.

iphone이나 ipad의 safari는 apple이 정한 검색 엔진만 고를 수 있어서, `safari/`에 safari 확장 프로그램이 들어 있는 작은 앱을 두었습니다. safari 검색 엔진은 google로 두면 확장 프로그램이 google, bing, duckduckgo, yahoo, ecosia, baidu 검색을 andromeda로 보냅니다. 자신의 apple 개발자 팀으로 xcode에서 빌드하고, 설정 › 앱 › safari › 확장 프로그램에서 켠 뒤 모든 웹사이트에서 허용하고, 팝업에 alles 주소를 입력하세요.

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
| andromeda | 웹을 검색하고, 원하면 출처가 달린 요약 받기. 브라우저 검색 엔진으로도 쓸 수 있음 |
| plan | 캘린더, 할 일, 알림, 카운트다운 관리하기 |
| inbox | 계정을 연결한 뒤 메일 읽고 연락처 관리하기 |
| docs | Markdown 노트와 일기 쓰기 |
| files | 로컬 또는 연결된 저장소, 오프라인 사본, 사진 둘러보기 |
| library | 글과 읽기 목록 저장하기 |
| health | 습관과 건강 기록 관리하기 |
| finance | 계좌, 거래, 예산, 구독 관리하기 |
| vault | 비밀 정보, 비밀번호, 패스키를 암호화해 보관하고, alles 확장 프로그램으로 chrome에서 로그인, 카드, 주소 채우기 |
| server | 상태, 접근 설정, 백업, 업데이트 확인하기 |

로컬 재무 원장에 직접 입력해 저장한 새 거래는 실행 취소할 수 있습니다. 실행 취소는 바로 그 거래만 삭제하며, 저장된 내용이 바뀌지 않았을 때만 가능합니다. 응답이 중간에 끊기면 같은 거래를 다시 시도할 수 있습니다. Actual 거래, 가져오기, 이체는 기존의 검토 및 삭제 절차를 따릅니다.

일부 기능은 먼저 연결해야 쓸 수 있습니다. 메일을 쓰려면 IMAP/SMTP 계정을 추가하고, 온라인 저장소나 은행은 해당 서비스를 연결하세요. aide를 쓰려면 **settings → models**에서 모델을 추가하세요. Ollama로 돌리는 로컬 모델도 쓸 수 있습니다.

메일에서 gmail, outlook, icloud, yahoo, fastmail 중 하나를 고르면 양식이 알아서 채워져요. gmail은 한 번만 하는 google cloud 설정 뒤에 google로 로그인하고, alles가 단계별로 안내해요(클라이언트 json을 내려받아 끌어다 놓으면 돼요). 은행 동기화는 **finance → bank connections**에 있어요(캐나다와 미국 대부분 은행은 plaid, 또는 simplefin). 휴대폰으로 aide에게 메시지를 보내려면 **settings → connections & tools**에서 telegram, imessage, discord를 켜면 돼요. 같은 페이지에서 node, pi, aide의 브라우저도 한 번에 설치할 수 있어요.

화면 언어는 english, français, español, 简体中文, 繁體中文, 日本語, 한국어, العربية 중에서 고를 수 있습니다. **설정 → 언어 및 지역**에서 바꾸세요.

앱의 자세한 동작, 아키텍처, API, 설정은 [specifications.md](../../specifications.md)에 있습니다.

## 데이터와 백업

설치한 alles는 데이터베이스와 관리하는 파일을 Linux에서는 `~/.local/share/alles/data`, macOS에서는 `~/Library/Application Support/Alles/data`에 둡니다. 위치는 `alles status`로 확인할 수 있습니다. 소스에서 실행하면 `data/`를 쓰고, `ALLES_DATA`를 설정했다면 그 위치를 씁니다. 이 폴더는 비공개로 두고 꼭 백업하세요. 외부 제공자는 각 연결을 통해 보낸 요청을 받습니다.

문서와 파일은 눈에 보이는 폴더 하나 `~/Alles`에 있고 문서는 `~/Alles/Docs`에 있어서, 쓴 것은 모두 파일에서 찾을 수 있습니다. 매일 백업은 데이터 폴더 옆, 보이지 않는 곳에 저장됩니다. 11월 이전 설치는 `alles update accept`(또는 `alles folders move`)를 실행하면 이 구성으로 옮겨집니다. 직접 고른 폴더나 다른 디스크에 있는 폴더는 그대로 두고, `alles doctor`가 이유를 알려 줍니다.

**settings → backup**을 열면 암호화된 백업을 내려받을 수 있습니다. 기존 HTTPS WebDAV 폴더나 S3 호환 버킷으로 직접 보낼 수도 있고, 처음 설정할 때 매일 로컬 백업을 켜 둘 수도 있습니다. 앱이 작동하지 않을 때도 꺼낼 수 있도록 복구 키는 alles 밖에 보관하세요.

alles는 백업을 확인하고 복원을 준비한 뒤에 적용합니다. 앱을 멈춘 다음 안내되는 명령을 따르세요. 기존 설치를 옮기기 전에 [백업과 복원 상세 내용](../../specifications.md#your-data-where-everything-lives)을 읽어 보세요.

## 업데이트와 제거

`alles update`는 최신 버전을 설치하고 이전 버전을 남겨 두므로, `alles update rollback`으로 데이터와 함께 이전 상태로 되돌릴 수 있습니다. `alles uninstall`은 alles를 제거하지만 개인 데이터는 남겨 둡니다. `alles help`로 모든 명령을 볼 수 있습니다. `alles status`는 릴리스를 짧은 커밋으로 보여 주고 새 릴리스가 나오면 알려 줍니다. `alles tools`는 aide가 쓸 수 있는 것(node, pi, aide의 브라우저)을 보여 주고 `alles tools install`로 설치합니다. `alles ask`와 `alles chat`으로 터미널에서 aide와 대화할 수 있습니다. `alles logs --level warn --since 1h`는 로그를 필요한 부분만 남기고, `alles backup`은 암호화된 백업을 만들며, `alles dump`는 비밀 정보 없이 버그 신고용 요약을 출력합니다.

alles는 FastAPI, SQLite, 순수 JavaScript, CSS로 만들었습니다. 프런트엔드 빌드 단계는 없습니다. 기술적인 내용은 [specifications.md](../../specifications.md)에 있습니다.

## 릴리스 기록

[davinci](../../docs/releases/davinci.md)에는 완료된 일상 작업 흐름 마일스톤이 기록되어 있습니다.

## 크레딧과 라이선스

aide는 [odysseus](https://github.com/pewdiepie-archdaemon/odysseus)에서 영감을 받았습니다. alles는 독립적으로 구현한 프로젝트입니다. [acknowledgments.md](../../ACKNOWLEDGMENTS.md)에서 그 프로젝트와 alles가 사용하는 다른 작업들의 출처를 밝힙니다. 서드파티 라이선스는 [서드파티 고지](../../THIRD_PARTY_NOTICES.md)에 있습니다.

alles는 [MIT 라이선스](../../LICENSE)로 배포됩니다.

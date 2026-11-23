# Hi-Fi Workshop Backend (Comet API)

Hi-Fi Workshop 캡스톤 프로젝트의 Comet 웹 인터페이스용 FastAPI 서버다. Python 3.11 이상, FastAPI, Pydantic v2를 사용한다.

**현재는 2-B 단계다.** 오디오 엔진은 두 가지 중 하나다.

- `mock`(기본값): 프로세스 메모리 안의 Mock 엔진. 라이브러리는 가상의 곡 목록이고 소리를 재생하지 않는다. 서버를 다시 시작하면 상태가 초기화된다.
- `mpd`: 실행 중인 MPD 서버에 TCP로 연결한다. Queue, 재생 제어, 라이브러리, 현재 곡과 재생 상태를 MPD에서 읽고 MPD에 명령한다. 상태는 MPD가 가지므로 서버를 다시 시작해도 유지된다.

어느 쪽이든 DSP(CamillaDSP)와 장치 정보(`/api/device`)는 아직 Mock이다. 그래서 `GET /api/system`의 `simulated`는 계속 `true`이고 `dataSource`는 `mock`이다. MPD 엔진의 연결 여부는 `audioEngine.connected`로 따로 알린다. 이 서버는 MPD의 오디오 출력(ALSA, DAC)을 확인하지 않으며, DAC 출력은 검증되지 않았다.

## 시작하기

가상환경은 이 폴더의 `.venv`에만 만든다.

```sh
python3 -m venv .venv            # Python 3.11 이상. uv 사용 시: uv venv --python 3.12 .venv
.venv/bin/pip install -r requirements-dev.txt   # uv 사용 시: uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
.venv/bin/python -m pytest
```

- API 문서(Swagger UI): http://127.0.0.1:8000/api/docs
- 프론트엔드는 `hifi-workshop-frontend`에서 `npm run dev:http`로 실행한다. Vite가 `/api`를 이 서버로 전달한다.

환경 변수는 [.env.example](.env.example)에 있다. 서버가 `.env` 파일을 직접 읽지는 않으므로 셸에서 지정한다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `COMET_AUDIO_ENGINE` | `mock` | `mock` 또는 `mpd` |
| `COMET_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 브라우저가 프록시 없이 직접 호출할 때 허용할 Origin |
| `COMET_DEV_API` | mock 엔진일 때만 켜짐 | `/api/dev/*` 사용 여부. MPD 엔진은 `/dev/source`·`/dev/reset`을 지원하지 않는다(501) |
| `COMET_MPD_HOST` | `127.0.0.1` | MPD 주소 |
| `COMET_MPD_PORT` | `6600` | MPD 포트. Raspberry Pi의 테스트 인스턴스는 `6601` |
| `COMET_MPD_TIMEOUT` | `3` | MPD 명령 하나를 기다리는 시간(초). 프론트 요청 제한 4초보다 짧게 둔다 |

### Raspberry Pi에서 MPD로 실행

```sh
COMET_AUDIO_ENGINE=mpd COMET_MPD_HOST=127.0.0.1 COMET_MPD_PORT=6601 COMET_DEV_API=0 \
  .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

실장비 검증 절차는 [docs/raspberry-pi-mpd-verification.md](docs/raspberry-pi-mpd-verification.md)에 있다.

### 테스트

`python -m pytest`는 실제 MPD 없이 돈다. MPD 어댑터 테스트는 `tests/fake_mpd.py`의 가짜 MPD 서버(127.0.0.1의 임의 포트)를 상대로 프로토콜까지 주고받는다. 실제 MPD를 상대로 하는 `tests/test_mpd_live.py`는 `COMET_MPD_LIVE=1`일 때만 실행된다.

## 구조

```
app/
  main.py            FastAPI 앱, 오류 응답 형식, 라우터 등록
  config.py          환경 변수 설정
  errors.py          도메인 오류 (HTTP 상태와 오류 코드)
  api/               라우터: system, library, player, queue, signal_chain, device, dev
  schemas/           Pydantic 모델. 프론트 src/api/types.ts와 같은 구조(JSON은 camelCase)
  services/          엔진과 무관한 규칙: 재생 상태 전이, Queue, Signal Chain 검증
  adapters/
    base.py          AudioEngine · DspEngine · DeviceProbe 인터페이스
    mock/            Mock 구현과 가상 라이브러리(data/library.json)
    mpd/             MPD 프로토콜 클라이언트(client.py, 표준 라이브러리만 사용)와 AudioEngine 구현(engine.py)
tests/               pytest + FastAPI TestClient, 가짜 MPD 서버(fake_mpd.py)
docs/                Raspberry Pi 실장비 검증 절차
```

### 동시성 전제: 단일 프로세스, 단일 워커

이 서버는 **프로세스 하나, 워커 하나**로 실행해야 한다. `uvicorn`의 기본값이 워커 1개이므로 위 명령을 그대로 쓰면 된다. `--workers 2` 이상이나 gunicorn 다중 워커, 여러 인스턴스 실행은 지원하지 않는다.

- 모든 상태(Queue, 재생 위치, Signal Chain)가 프로세스 메모리에 있다. 워커가 여럿이면 워커마다 상태가 따로 생겨 요청마다 다른 답이 나온다.
- 요청 처리 함수는 await가 없는 `async def`라서 이벤트 루프에서 한 번에 하나씩 실행된다. 그래서 메모리 상태에 잠금이 없다.
- MPD 엔진은 처리 함수 안에서 MPD 소켓 I/O를 블로킹으로 수행한다. 그동안 이벤트 루프가 멈추므로 요청은 여전히 하나씩 처리되고, MPD 연결 하나를 두 요청이 동시에 쓰지 않는다. localhost에서는 왕복이 밀리초 단위이고, MPD가 응답하지 않으면 `COMET_MPD_TIMEOUT` 뒤에 503으로 끝난다. 처리 함수에 `await`를 넣거나 `def`(스레드 풀)로 바꾸면 이 전제가 깨지므로 잠금이 필요해진다.

## API

모든 경로는 `/api` 아래에 있다. 재생·Queue 명령은 변경 후의 `PlaybackState` 전체를, Signal Chain 명령은 `SignalChainState` 전체를 반환한다.

| 영역 | 메서드와 경로 | 본문 |
|---|---|---|
| System | `GET /health` | |
| | `GET /system` | |
| | `GET /state` — playback, signalChain, device, system을 한 번에 | |
| Library | `GET /library` · `/library/albums` · `/library/albums/{id}` | |
| | `GET /library/artists` · `/library/artists/{name}` | |
| | `GET /library/tracks` · `/library/tracks/{id}` | |
| Player | `GET /player` | |
| | `POST /player/play` · `/pause` · `/stop` · `/next` · `/previous` | |
| | `POST /player/seek` | `{"seconds": 120}` |
| | `POST /player/play-track` — 곡 선택 | `{"trackId": "track-005"}` |
| Queue | `GET /queue` | |
| | `PUT /queue` — 교체 후 첫 곡 재생(앨범 단위) | `{"trackIds": ["track-001", …]}` |
| | `DELETE /queue` — 비우기 | |
| | `POST /queue/items` (201) — 끝에 추가 | `{"trackId": "track-002"}` |
| | `DELETE /queue/items/{itemId}` | |
| | `POST /queue/items/{itemId}/move` | `{"direction": -1}` 또는 `1` |
| | `POST /queue/items/{itemId}/play` | |
| Signal Chain | `GET /signal-chain` · `GET /signal-chain/limits` | |
| | `PUT /signal-chain/processing` | `{"enabled": true}` |
| | `POST /signal-chain/modules` (201) | `{"kind": "gain"｜"eq"｜"crossfeed"}` |
| | `PATCH /signal-chain/modules/{id}` | `{"enabled"?, "gain"?, "amount"?}` |
| | `DELETE /signal-chain/modules/{id}` | |
| | `POST /signal-chain/modules/{id}/move` | `{"direction": -1}` 또는 `1` |
| | `POST /signal-chain/modules/{id}/bands` (201) | |
| | `PATCH /signal-chain/modules/{id}/bands/{bandId}` | `{"frequency"?, "gain"?, "q"?}` |
| | `DELETE /signal-chain/modules/{id}/bands/{bandId}` | |
| Device | `GET /device` | |
| Dev (mock 전용) | `POST /dev/source` — 입력 소스 미리보기 | `{"source": "bluetooth"}` |
| | `POST /dev/reset` — 초기 상태로 | |

### 재생 상태 전이

| 현재 | play | pause | stop | seek |
|---|---|---|---|---|
| `paused` | `playing` | 변화 없음 | `stopped`, 0초 | `paused`, 지정 위치 |
| `playing` | 변화 없음 | `paused` | `stopped`, 0초 | `playing`, 지정 위치 |
| `stopped` | `playing`, 0초부터 | 변화 없음 | 변화 없음 | `paused`, 지정 위치 |

- 재생 위치는 서버 시계로 계산한다(`재생 시작 시점의 위치 + 경과 시간`). 응답 시점의 값이 `position`(초, 소수)이다.
- 곡이 끝나면 다음 곡으로 넘어가고, 마지막 곡이 끝나면 그 곡에 머문 채 `stopped`, 0초가 된다.
- `next`/`previous`는 상태를 유지한 채 곡만 바꾼다. 이동할 곡이 없으면 409다.
- Queue가 비어 있으면 `play`는 409 `queue_empty`, `seek`는 409 `not_seekable`이다. `stop`과 `pause`는 200이다.
- 선택된 곡이 없고 Queue에 곡이 있으면 `play`는 첫 곡을 재생한다.
- 현재 곡을 Queue에서 제거하면 다음 곡으로 이어지고, 다음 곡이 없으면 선택 없이 `stopped`가 된다.
- 입력 소스가 `local`·`spotify`가 아니면 재생 명령은 409 `not_controllable`이다.

### 검증 범위

프론트 `src/api/types.ts`의 `limits`와 같은 값이다. 범위를 벗어나면 값을 잘라 맞추지 않고 422로 거부한다.

| 값 | 범위 |
|---|---|
| Gain (모듈, EQ 밴드) | −12 ~ +12 dB |
| EQ 주파수 | 20 ~ 20000 Hz |
| EQ Q | 0.1 ~ 10 |
| Crossfeed | 0 ~ 100 % |
| EQ 밴드 수 | 1 ~ 8 (9번째 추가와 마지막 밴드 삭제는 409) |
| Seek | 0 ~ 곡 길이 |

### 오류 형식

```json
{"error": {"code": "queue_item_not_found", "message": "Queue item 999 does not exist."}}
```

| 상태 | 의미 |
|---|---|
| 404 | 대상(곡, Queue 항목, 모듈, 밴드, 경로)이 없음 |
| 409 | 형식은 맞지만 현재 상태에서 불가능 |
| 422 | 값이 잘못됨. `validation_error`에는 `details`(필드별 메시지)가 붙는다 |
| 501 | 설정된 엔진이 지원하지 않음 (MPD 엔진의 dev 기능) |
| 502 | MPD가 명령을 거부함 (`mpd_error`, 메시지에 MPD의 ACK 내용) |
| 503 | MPD에 연결할 수 없음 (`mpd_unavailable`). 다음 요청에서 다시 연결을 시도한다 |

### 동기화용 필드

- `revision`: `PlaybackState`와 `SignalChainState`에 붙는다. 재생 위치를 제외한 상태가 바뀔 때마다 증가한다. 클라이언트는 더 낮은 값을 가진 응답을 버린다.
- `serverId`: 서버를 시작할 때마다 새로 정해진다. 값이 바뀌면 클라이언트는 캐시한 상태와 `revision`을 버린다.

## MPD 엔진

`app/adapters/mpd/engine.py`가 `AudioEngine`을 MPD 명령으로 옮긴다. 서비스와 라우터, 응답 형식은 Mock과 같다.

| 동작 | MPD 명령 |
|---|---|
| 상태 | `status`, Queue 버전(`playlist`)이 바뀌었거나 재연결했을 때만 `playlistinfo` |
| 라이브러리 | `stats`의 `db_update`가 바뀌었을 때만 `listallinfo` (그 외에는 캐시) |
| play | 일시정지면 `pause 0`, 정지면 `playid <현재>`, 항목 지정 시 `playid <id>` |
| pause · stop | `pause 1`(재생 중일 때만) · `stop` |
| next · previous | `playid <대상>` + 이전 상태 복원(`pause 1` 또는 `stop`)을 한 command list로. MPD의 `next`/`previous`는 쓰지 않는다 |
| seek | 재생 중 `seekcur`, 일시정지 `seekcur` + `pause 1`, 정지 `seekid <현재> <초>` + `pause 1` |
| Queue | `addid <uri> [위치]`, `deleteid`, `moveid`, `clear`. 현재 곡을 지우면 다음 곡을 같은 상태로 선택 |

- **식별자**: 곡 id는 MPD URI(`music_directory` 기준 상대 경로, 예: `test/sine-44k.wav`), 앨범 id는 앨범 아티스트와 제목의 해시, Queue 항목 id는 MPD의 song id다. URI에 `/`가 있으므로 `/library/tracks/{id}`는 경로 전체를 id로 받는다.
- **태그가 없는 파일**: 제목은 파일 이름, 앨범은 폴더 이름, 아티스트는 `Unknown Artist`, 연도는 `0`이다. 커버 이미지는 아직 없어서 `art`는 빈 문자열이고 프론트는 기본 아이콘을 보여 준다.
- **포맷**: 재생·일시정지 중에는 `status`의 `audio`, 정지 중에는 곡의 `Format`을 쓴다. 코덱은 파일 확장자다(`WAV`, `FLAC`).
- **추가 제한**: `addid`에는 MPD 데이터베이스에 있는 URI만 보낸다. 클라이언트가 보낸 URL이나 로컬 경로는 404다.
- **연결**: 첫 요청에서 연결하고 같은 연결을 재사용한다. MPD가 유휴 연결을 끊었으면(`connection_timeout`) 한 번 다시 연결해 명령을 다시 보낸다. 응답 대기 중 시간 초과는 명령이 이미 실행됐을 수 있어 다시 보내지 않는다.
- **revision**: MPD의 Queue 버전, 재생 상태, 현재 곡, 포맷이 바뀌거나 이 서버가 명령을 보낼 때마다 증가한다. `mpc` 같은 다른 클라이언트의 변경도 다음 조회 때 반영된다.
- MPD의 `random`, `single`, `consume`, `repeat` 설정은 건드리지 않는다. `random`이 켜져 있으면 곡이 끝난 뒤의 순서가 `hasNext`가 가정하는 Queue 순서와 다를 수 있다.

## 남은 Mock 구성 요소

- `DspEngine` → CamillaDSP. 검증을 통과한 Signal Chain을 변경 때마다 `apply()`로 받는다.
- `DeviceProbe` → Raspberry Pi의 ALSA·네트워크·시스템 정보.

`app/adapters/base.py`의 인터페이스를 구현하고 `app/services/container.py`의 `build_services()`에서 고르면 된다.

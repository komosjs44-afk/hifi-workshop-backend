# Hi-Fi Workshop Backend (Comet API)

Hi-Fi Workshop 캡스톤 프로젝트의 Comet 웹 인터페이스용 FastAPI 서버다. Python 3.11 이상, FastAPI, Pydantic v2를 사용한다.

**현재는 2-A 단계다.** 서버는 프로세스 메모리 안의 Mock 오디오 엔진으로 동작한다. MPD, ALSA 장치, DSP(CamillaDSP), DAC에는 연결되지 않으며 소리를 재생하지 않는다. 라이브러리는 가상의 곡 목록이고, 장치·포맷·네트워크 값은 예시다. API는 이 사실을 `GET /api/system`의 `simulated`, `connected: false`와 `GET /api/device`의 `simulated: true`로 알린다. 서버를 다시 시작하면 모든 상태가 초기화된다.

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
| `COMET_AUDIO_ENGINE` | `mock` | `mpd`는 자리만 있는 어댑터이며 모든 오디오 요청에 501을 반환한다 |
| `COMET_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 브라우저가 프록시 없이 직접 호출할 때 허용할 Origin |
| `COMET_DEV_API` | mock 엔진일 때만 켜짐 | `/api/dev/*` 사용 여부 |

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
    mpd/             MPD 어댑터 자리(미구현, 501)
tests/               pytest + FastAPI TestClient
```

### 동시성 전제: 단일 프로세스, 단일 워커

이 서버는 **프로세스 하나, 워커 하나**로 실행해야 한다. `uvicorn`의 기본값이 워커 1개이므로 위 명령을 그대로 쓰면 된다. `--workers 2` 이상이나 gunicorn 다중 워커, 여러 인스턴스 실행은 지원하지 않는다.

- 모든 상태(Queue, 재생 위치, Signal Chain)가 프로세스 메모리에 있다. 워커가 여럿이면 워커마다 상태가 따로 생겨 요청마다 다른 답이 나온다.
- 요청 처리 함수는 await가 없는 `async def`라서 이벤트 루프에서 한 번에 하나씩 실행된다. 그래서 메모리 상태에 잠금이 없다.
- 실제 엔진을 붙이면서 블로킹 I/O(MPD 소켓 등)나 `await`가 처리 함수 안에 들어오면 이 전제가 깨진다. 그때는 잠금이나 전용 작업 스레드를 도입해야 한다.

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
| 501 | 설정된 엔진이 지원하지 않음 (`engine_not_implemented`, dev 기능 미지원) |

### 동기화용 필드

- `revision`: `PlaybackState`와 `SignalChainState`에 붙는다. 재생 위치를 제외한 상태가 바뀔 때마다 증가한다. 클라이언트는 더 낮은 값을 가진 응답을 버린다.
- `serverId`: 서버를 시작할 때마다 새로 정해진다. 값이 바뀌면 클라이언트는 캐시한 상태와 `revision`을 버린다.

## 실제 오디오 엔진으로 전환

`app/adapters/base.py`의 세 인터페이스를 구현하고 `app/services/container.py`의 `build_services()`에서 고르면 된다. 서비스와 라우터는 바꾸지 않는다.

- `AudioEngine` → MPD (Queue, 재생, 라이브러리). 메서드별 MPD 명령 대응은 `app/adapters/mpd/engine.py`에 적혀 있다.
- `DspEngine` → CamillaDSP. 검증을 통과한 Signal Chain을 변경 때마다 `apply()`로 받는다.
- `DeviceProbe` → Raspberry Pi의 ALSA·네트워크·시스템 정보.

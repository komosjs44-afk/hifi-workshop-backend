# Raspberry Pi 실장비 검증 절차 (2-B: FastAPI → MPD)

React → FastAPI → `MpdAudioEngine` → MPD 경로를 Raspberry Pi 5에서 확인하는 절차다.

**범위와 한계**

- 확인 대상은 MPD의 Queue·재생 제어·라이브러리·상태가 API로 정확히 오가는지다.
- MPD 출력은 Null Audio Output이다. 소리는 나지 않으며, **이 절차로 DAC(HiFiBerry DAC2 Pro) 출력은 검증되지 않는다.** DAC는 I²C 초기화 오류(-121)로 인식되지 않는 상태이며 이 단계의 범위 밖이다.
- MPD 설정 파일, 음악 디렉터리, WAV 테스트 파일은 읽기만 한다. 바뀌는 것은 MPD Queue와 재생 상태뿐이며, 1단계에서 백업하고 9단계에서 되돌린다.

아래 명령은 Pi의 백엔드 폴더(`hifi-workshop-backend`)에서 실행한다. MPD 포트는 `6601`이다.

## 1. 현재 MPD 상태 백업

```sh
mpc -p 6601 status                                  > ~/mpd-before-status.txt
mpc -p 6601 -f %file% playlist                       > ~/mpd-before-queue.txt
mpc -p 6601 outputs
```

- `outputs`에 Null 출력만 켜져 있는지 본다.
- `mpc -p 6601 status`의 `consume: off`를 확인한다. `consume`이 켜져 있으면 재생한 곡이 Queue에서 지워져 결과가 달라진다.

## 2. MPD 라이브러리 확인

```sh
mpc -p 6601 version
mpc -p 6601 stats
mpc -p 6601 -f '%file% | %time%' listall
```

44.1kHz·48kHz WAV 파일이 보여야 한다. 이때 보이는 경로(예: `test/sine-44k.wav`)가 API의 곡 `id`가 된다.

## 3. 코드 반영과 오프라인 테스트

```sh
.venv/bin/pip install -r requirements-dev.txt   # 새 패키지 없음. 기존 개발 의존성만
.venv/bin/python -m pytest -q
```

MPD가 없어도 통과하는 테스트다(가짜 MPD 서버 사용). 전부 통과해야 하며 `test_mpd_live.py`는 skip으로 표시된다.

## 4. 실제 MPD 대상 자동 테스트

```sh
COMET_MPD_LIVE=1 COMET_MPD_HOST=127.0.0.1 COMET_MPD_PORT=6601 \
  .venv/bin/python -m pytest tests/test_mpd_live.py -s -q
```

확인 항목: 연결, 라이브러리에 WAV 2개 이상, 앨범 단위 Queue 교체, 재생 위치 증가(2.5초 대기), 일시정지 중 위치 고정, next/previous 후 일시정지 유지, seek, stop, Queue 이동·삭제·비우기. 테스트가 끝나면 Queue가 테스트 전 상태로 복원된다. `-s` 출력에 MPD 버전, WAV 길이, 포맷, "seek while stopped" 결과가 찍힌다.

## 5. 서버 실행

```sh
COMET_AUDIO_ENGINE=mpd COMET_MPD_HOST=127.0.0.1 COMET_MPD_PORT=6601 COMET_DEV_API=0 \
  .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

다른 터미널에서 아래를 진행한다. `jq`가 없으면 `python3 -m json.tool`을 쓴다.

```sh
API=http://127.0.0.1:8000/api
```

## 6. API 수동 확인 (mpc와 대조)

| # | 명령 | 기대 결과 | mpc 대조 |
|---|---|---|---|
| 1 | `curl -s $API/system \| jq .audioEngine` | `kind: "mpd"`, `connected: true`, `simulated: false`, 설명에 MPD 버전 | |
| 2 | `curl -s $API/system \| jq '{simulated, dataSource, devApi}'` | `true`, `"mock"`, `false` (DSP·장치는 아직 Mock) | |
| 3 | `curl -s $API/library \| jq '.tracks[] \| {id, duration}'` | WAV 파일과 길이(초) | `mpc listall` |
| 4 | `curl -s -X PUT $API/queue -H 'content-type: application/json' -d '{"trackIds":["<WAV1 id>","<WAV2 id>"]}' \| jq '{status, position, format, id: .track.id}'` | `playing`, 0, 포맷(예: `WAV / 16-bit / 44.1 kHz`) | `mpc -p 6601 status` → `[playing]` |
| 5 | `curl -s $API/player \| jq .position` 를 2초 간격으로 두 번 | 약 2 증가 | `mpc -p 6601 status`의 시간 |
| 6 | `curl -s -X POST $API/player/pause \| jq .status` | `paused`, 이후 position 고정 | `[paused]` |
| 7 | `curl -s -X POST $API/player/next \| jq '{status, id: .track.id}'` | `paused`, 두 번째 WAV | `mpc current` |
| 8 | `curl -s -X POST $API/player/previous \| jq '{status, id: .track.id}'` | `paused`, 첫 번째 WAV | |
| 9 | `curl -s -X POST $API/player/seek -H 'content-type: application/json' -d '{"seconds":3}' \| jq '{status, position}'` | `paused`, 3 | |
| 10 | `curl -s -X POST $API/player/play \| jq .status` | `playing`, 3초부터 | `[playing]` |
| 11 | `curl -s -X POST $API/player/stop \| jq '{status, position, currentId}'` | `stopped`, 0, 곡 선택 유지 | `mpc status`에 재생 표시 없음 |
| 12 | `curl -s -X POST $API/queue/items -H 'content-type: application/json' -d '{"trackId":"<WAV1 id>"}' -o /dev/null -w '%{http_code}\n'` | `201` | `mpc playlist` 3곡 |
| 13 | `curl -s $API/queue \| jq '.items[] \| .id'` 로 id 확인 후 `curl -s -X POST $API/queue/items/<id>/move -H 'content-type: application/json' -d '{"direction":-1}'` | 순서 변경 | `mpc playlist` |
| 14 | `curl -s -X DELETE $API/queue/items/<id> \| jq '.queue \| length'` | 1 감소 | `mpc playlist` |
| 15 | `mpc -p 6601 play` 실행 후 `curl -s $API/player \| jq '{status, revision}'` | `playing`, revision 증가 (외부 변경 반영) | |
| 16 | `curl -s -X POST $API/queue/items -H 'content-type: application/json' -d '{"trackId":"http://example.com/a.mp3"}'` | 404 `track_not_found` (DB 밖 URI 거부) | Queue 변화 없음 |
| 17 | `curl -s -X POST $API/dev/reset -o /dev/null -w '%{http_code}\n'` | `404` (`COMET_DEV_API=0`) | |

정지 상태에서의 seek(`stop` 후 `seek`)는 MPD의 동작에 따라 `paused`(기대) 또는 `stopped`로 끝날 수 있다. 결과를 기록해 둔다.

## 7. 연결 오류 확인

실행 중인 MPD는 멈추지 않는다. 비어 있는 포트를 가리키는 두 번째 서버로 확인한다.

```sh
COMET_AUDIO_ENGINE=mpd COMET_MPD_PORT=6699 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 &
curl -s http://127.0.0.1:8001/api/health                      # 200
curl -s http://127.0.0.1:8001/api/system | jq .audioEngine    # connected: false, "not reachable"
curl -s -w ' %{http_code}\n' http://127.0.0.1:8001/api/player   # {"error":{"code":"mpd_unavailable",...}} 503
curl -s -w ' %{http_code}\n' http://127.0.0.1:8001/api/state    # 503
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/api/signal-chain  # 200
kill %1
```

(선택) MPD 재시작 후 자동 재연결: MPD 인스턴스를 직접 다시 시작할 수 있을 때만 한다. 재시작 중 `/api/player`는 503, 재시작 후 첫 요청부터 200이어야 한다. 서버는 다시 시작하지 않는다.

## 8. 브라우저(React) 확인

LG 그램에서 프론트엔드를 Pi의 API로 연결한다. 프론트 코드는 바꾸지 않는다.

```powershell
cd hifi-workshop-frontend
$env:VITE_API_PROXY_TARGET="http://<Pi IP>:8000"; npm run dev:http
```

- 설정 화면: `오디오 엔진: mpd`. DSP·장치가 Mock이므로 "Mock 오디오 엔진" 안내 문구와 데모 배지가 함께 보인다(아래 "알려진 차이" 참고).
- 라이브러리: WAV 파일이 폴더 이름의 앨범으로 보이고 커버는 기본 아이콘이다.
- 재생·일시정지·이전·다음·탐색, Queue 추가·삭제·이동이 `mpc -p 6601 status`/`playlist`와 일치한다.
- 5번 서버를 멈추면 "연결 끊김"으로 바뀌고, 다시 띄우면 복구된다.

## 9. 복원

```sh
mpc -p 6601 clear
xargs -d '\n' -a ~/mpd-before-queue.txt -r mpc -p 6601 add
mpc -p 6601 status    # ~/mpd-before-status.txt와 비교. 재생 상태가 달랐다면 mpc play/pause/stop으로 맞춘다
```

## 결과 기록 양식

| 항목 | 결과 | 비고 |
|---|---|---|
| 오프라인 pytest | | 통과 수 |
| live pytest | | MPD 버전, 정지 중 seek 결과 |
| 6번 1~17 | | 실패 항목 번호 |
| 7번 연결 오류 | | |
| 8번 브라우저 | | |
| DAC 출력 | **미검증** | Null 출력 사용. DAC2 Pro I²C -121 |

## 알려진 차이

- `GET /api/system`의 `simulated`는 DSP와 장치 정보가 Mock이므로 `true`다. 프론트 설정 화면의 안내 문구("MPD … 연결되어 있지 않으며")는 Mock 엔진 기준이라 MPD 엔진에서는 정확하지 않다. 문구 수정은 프론트 작업으로 남긴다.
- 장치 화면의 출력 장치·PCM·MPD 상태 값은 Mock 예시다. 실제 값이 아니다.
- 태그 없는 WAV는 연도가 `0`으로 표시된다.

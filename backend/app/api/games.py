import logging

from fastapi import APIRouter, HTTPException, Request

from ..domain.models import TurnRequest, PolicyPreviewRequest, DiplomacyRequest
from ..services.game_service import ServiceError

router = APIRouter()
logger = logging.getLogger("shengzhi")

@router.get('/api/emperors')
def emperor_library():
    from ..domain.emperors import EMPERORS,CATALOG_VERSION
    return {'catalog_version':CATALOG_VERSION,'count':len(EMPERORS),'emperors':[
        {k:e[k] for k in ('id','name','dynasty','era','themes','facts','sources')} for e in EMPERORS]}


def _service_error_to_http(exc: ServiceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "retryable": exc.retryable,
        },
    )


def get_service(request: Request):
    return request.app.state.game_service


@router.get("/api/games/{game_id}/emperor")
def get_emperor_review(game_id: str, request: Request) -> dict:
    try:
        return get_service(request).get_emperor_review(game_id)
    except ServiceError as exc:
        raise _service_error_to_http(exc) from exc


@router.post("/api/games/{game_id}/emperor")
def generate_emperor_review(game_id: str, request: Request) -> dict:
    try:
        return get_service(request).generate_emperor_review(game_id)
    except ServiceError as exc:
        raise _service_error_to_http(exc) from exc


@router.post("/api/games", status_code=201)
def create_game(request: Request) -> dict:
    return get_service(request).create_game()


@router.post("/api/games/{game_id}/opening")
def opening_briefing(game_id: str, request: Request) -> dict:
    try:
        return get_service(request).generate_opening_briefing(game_id)
    except ServiceError as exc:
        raise _service_error_to_http(exc) from exc


@router.get("/api/games/{game_id}")
def get_game(game_id: str, request: Request) -> dict:
    detail = get_service(request).get_game_detail(game_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "GAME_NOT_FOUND", "message": "未找到该局存档,可新建一局。"},
        )
    return detail


@router.get('/api/games/{game_id}/events/audit')
def get_event_audit(game_id: str, request: Request) -> dict:
    import json
    row=get_service(request).db.get_game(game_id)
    if row is None:
        raise HTTPException(status_code=404,detail={'code':'GAME_NOT_FOUND','message':'未找到该局存档。'})
    state=json.loads(row.get('events_json') or '{}')
    return {'version':state.get('version'),'seed':state.get('seed'),
            'initial_state':state.get('initial_state'),'audit':state.get('audit',[])}


@router.post("/api/games/{game_id}/turns")
def submit_turn(game_id: str, body: TurnRequest, request: Request) -> dict:
    try:
        return get_service(request).submit_turn(
            game_id=game_id,
            request_id=body.request_id,
            expected_revision=body.expected_revision,
            policy_text=body.policy_text,
            expected_turn=body.expected_turn,
        )
    except ServiceError as exc:
        if exc.status_code >= 500:
            logger.warning("turn failed game=%s code=%s", game_id, exc.code)
        raise _service_error_to_http(exc) from exc

@router.post('/api/games/{game_id}/preview')
def preview_order(game_id: str,body: PolicyPreviewRequest,request: Request) -> dict:
    try:
        return get_service(request).preview_order(game_id,body.expected_revision,body.policy_text)
    except ServiceError as exc:
        raise _service_error_to_http(exc) from exc

@router.post('/api/games/{game_id}/diplomacy')
def negotiate(game_id: str,body: DiplomacyRequest,request: Request) -> dict:
    try:
        return get_service(request).negotiate(game_id,body.request_id,body.expected_revision,body.action,body.text,body.proposal_id)
    except ServiceError as exc:
        raise _service_error_to_http(exc) from exc

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.schemas import SearchRequest, SearchResponse
from app.container import Container, get_container
from app.retrieval.hybrid import RetrievalResult

router = APIRouter()


@router.post("/api/search", response_model=SearchResponse)
def search(
    body: SearchRequest, request: Request, container: Annotated[Container, Depends(get_container)]
) -> RetrievalResult:
    result = container.retriever.search(
        body.query,
        config=body.model_dump(exclude={"query", "filters"}, exclude_none=True),
        filters=body.filters,
    )
    return result

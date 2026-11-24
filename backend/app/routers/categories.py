from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import WorkspaceContext, workspace_context
from app.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import categories as categories_service
from app.services.categories import CategoryError

router = APIRouter(prefix="/categories", tags=["categories"])


def _raise_http(exc: CategoryError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("", response_model=list[CategoryOut])
def list_categories(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(workspace_context("bills:read")),
):
    """List the user's categories (defaults first).

    Read-only: defaults are seeded at registration and by the migration for
    pre-existing users, so GET never writes.
    """
    return categories_service.list_categories(
        db, ws.owner_id, include_archived=include_archived
    )


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreate,
    db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(workspace_context("bills:write")),
):
    try:
        category = categories_service.create_category(db, ws.owner_id, body.name)
    except CategoryError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(category)
    return category


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(workspace_context("bills:write")),
):
    """Rename and/or archive a category. Omitted fields are left unchanged."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        try:
            category = categories_service.get_for_user(
                db, ws.owner_id, category_id, allow_archived=True
            )
        except CategoryError as exc:
            _raise_http(exc)
        return category
    try:
        if "name" in updates and updates["name"] is not None:
            category = categories_service.rename_category(
                db, ws.owner_id, category_id, updates["name"]
            )
        else:
            category = categories_service.get_for_user(
                db, ws.owner_id, category_id, allow_archived=True
            )
        if "is_archived" in updates and updates["is_archived"] is not None:
            category = categories_service.set_archived(
                db, ws.owner_id, category_id, updates["is_archived"]
            )
    except CategoryError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(workspace_context("bills:write")),
):
    """Delete an unused category. In-use categories must be archived instead."""
    try:
        categories_service.delete_category(db, ws.owner_id, category_id)
    except CategoryError as exc:
        _raise_http(exc)
    db.commit()

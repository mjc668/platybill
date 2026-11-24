from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import require_session_auth, resolve_user_workspace
from app.core.ratelimit import rate_limited_by_user
from app.core.scopes import ALL_SCOPES
from app.core.security import PasswordTooLongError, hash_password
from app.models.bill import BillTemplate
from app.models.family import Family, FamilyInvite, FamilyMember
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.family import (
    FamilyInviteOut,
    FamilyMemberAddRequest,
    FamilyMemberOut,
    FamilyMemberUpdateRequest,
    FamilyOverviewOut,
)
from app.services.categories import ensure_default_categories

router = APIRouter(prefix="/family", tags=["family"])

_INVITE_TTL_DAYS = 7


def _invite_out(invite: FamilyInvite, family: Family, owner: User) -> FamilyInviteOut:
    return FamilyInviteOut(
        id=invite.id,
        family_id=family.id,
        family_name=family.name,
        owner_email=owner.email,
        email=invite.email,
        scopes=list(invite.scopes or []),
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


def _get_or_create_owned_family(db: Session, me: User) -> Family:
    membership = db.query(FamilyMember).filter(FamilyMember.user_id == me.id).first()
    if membership is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the family owner can manage family members",
        )
    family = db.query(Family).filter(Family.owner_id == me.id).first()
    if family is None:
        family = Family(owner_id=me.id, name="My Family")
        db.add(family)
        db.flush()
    return family


@router.get("", response_model=FamilyOverviewOut)
def get_family(
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    owner_id, owner, my_scopes, is_owner = resolve_user_workspace(db, me)

    family = (
        db.query(Family)
        .options(
            selectinload(Family.members).selectinload(FamilyMember.user),
            selectinload(Family.invites),
        )
        .filter(Family.owner_id == owner_id)
        .first()
    )

    members: list[FamilyMemberOut] = []
    outgoing: list[FamilyInviteOut] = []
    if family is not None:
        members = [
            FamilyMemberOut(
                id=m.id,
                user_id=m.user_id,
                email=m.user.email,
                scopes=list(m.scopes or []),
                created_at=m.created_at,
            )
            for m in sorted(family.members, key=lambda x: x.created_at)
        ]
        if is_owner:
            outgoing = [
                _invite_out(inv, family, owner)
                for inv in family.invites
                if inv.expires_at > now
            ]

    incoming_rows = (
        db.query(FamilyInvite)
        .options(selectinload(FamilyInvite.family).selectinload(Family.owner))
        .filter(
            FamilyInvite.email == me.email.lower(),
            FamilyInvite.expires_at > now,
        )
        .all()
    )
    incoming = [_invite_out(inv, inv.family, inv.family.owner) for inv in incoming_rows]

    return FamilyOverviewOut(
        is_owner=is_owner,
        family_id=family.id if family else None,
        family_name=family.name if family else None,
        owner_email=owner.email if family else None,
        my_scopes=sorted(my_scopes) if not is_owner else list(ALL_SCOPES),
        members=members,
        outgoing_invites=outgoing,
        incoming_invites=incoming,
    )


@router.post(
    "/members", response_model=FamilyOverviewOut, status_code=status.HTTP_201_CREATED
)
def add_family_member(
    body: FamilyMemberAddRequest,
    me: User = Depends(require_session_auth),
    _rl: None = Depends(rate_limited_by_user("family")),
    db: Session = Depends(get_db),
):
    if body.email == me.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already the family owner",
        )

    family = _get_or_create_owned_family(db, me)
    existing_user = db.query(User).filter(User.email == body.email).first()

    if existing_user is not None:
        if (
            db.query(FamilyMember)
            .filter(FamilyMember.user_id == existing_user.id)
            .first()
            is not None
            or db.query(Family).filter(Family.owner_id == existing_user.id).first()
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user already belongs to a family",
            )
        if (
            db.query(BillTemplate.id)
            .filter(BillTemplate.user_id == existing_user.id)
            .first()
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user already has their own bills and cannot join another family",
            )
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=_INVITE_TTL_DAYS)
        invite = (
            db.query(FamilyInvite)
            .filter(
                FamilyInvite.family_id == family.id,
                FamilyInvite.email == body.email,
            )
            .first()
        )
        if invite is not None:
            invite.scopes = body.scopes
            invite.expires_at = expires_at
        else:
            db.add(
                FamilyInvite(
                    family_id=family.id,
                    email=body.email,
                    scopes=body.scopes,
                    expires_at=expires_at,
                )
            )
        db.commit()
        return get_family(me=me, db=db)

    if not body.initial_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Account does not exist yet; provide an initial password to create it",
        )

    try:
        pw_hash = hash_password(body.initial_password)
    except PasswordTooLongError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password exceeds the 72-byte limit",
        )

    new_user = User(email=body.email, password_hash=pw_hash)
    db.add(new_user)
    db.flush()
    ensure_default_categories(db, new_user)
    db.add(
        FamilyMember(
            family_id=family.id,
            user_id=new_user.id,
            scopes=body.scopes,
        )
    )
    db.commit()
    return get_family(me=me, db=db)


@router.patch("/members/{member_id}", response_model=FamilyMemberOut)
def update_family_member(
    member_id: int,
    body: FamilyMemberUpdateRequest,
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    family = db.query(Family).filter(Family.owner_id == me.id).first()
    if family is None:
        raise HTTPException(status_code=404, detail="Family member not found")
    member = (
        db.query(FamilyMember)
        .options(selectinload(FamilyMember.user))
        .filter(FamilyMember.id == member_id, FamilyMember.family_id == family.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Family member not found")
    member.scopes = body.scopes
    db.commit()
    db.refresh(member)
    return FamilyMemberOut(
        id=member.id,
        user_id=member.user_id,
        email=member.user.email,
        scopes=list(member.scopes or []),
        created_at=member.created_at,
    )


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_family_member(
    member_id: int,
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    member = (
        db.query(FamilyMember)
        .options(selectinload(FamilyMember.family))
        .filter(FamilyMember.id == member_id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Family member not found")
    if member.family.owner_id != me.id and member.user_id != me.id:
        raise HTTPException(status_code=404, detail="Family member not found")
    db.delete(member)
    db.commit()


@router.post("/invites/{invite_id}/accept", response_model=MessageResponse)
def accept_family_invite(
    invite_id: int,
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    invite = (
        db.query(FamilyInvite)
        .filter(
            FamilyInvite.id == invite_id,
            FamilyInvite.email == me.email.lower(),
            FamilyInvite.expires_at > now,
        )
        .first()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found or expired")

    if (
        db.query(FamilyMember).filter(FamilyMember.user_id == me.id).first() is not None
        or db.query(Family).filter(Family.owner_id == me.id).first() is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already belong to a family",
        )
    if (
        db.query(BillTemplate.id).filter(BillTemplate.user_id == me.id).first()
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accounts with existing bills cannot join another family",
        )

    db.add(
        FamilyMember(
            family_id=invite.family_id,
            user_id=me.id,
            scopes=list(invite.scopes or []),
        )
    )
    db.delete(invite)
    db.commit()
    return MessageResponse(message="Joined family.")


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family_invite(
    invite_id: int,
    me: User = Depends(require_session_auth),
    db: Session = Depends(get_db),
):
    invite = (
        db.query(FamilyInvite)
        .options(selectinload(FamilyInvite.family))
        .filter(FamilyInvite.id == invite_id)
        .first()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.family.owner_id != me.id and invite.email != me.email.lower():
        raise HTTPException(status_code=404, detail="Invite not found")
    db.delete(invite)
    db.commit()

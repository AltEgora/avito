import enum
import os
import random
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import (
    ForeignKey,
    String,
    Table,
    create_engine,
    func,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    Session,
    declarative_base,
    joinedload,
    relationship,
    selectinload,
    sessionmaker,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://pr_user:добрыйдень@localhost:5432/pr_db"
)

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class PRStatus(str, enum.Enum):
    OPEN = "OPEN"
    MERGED = "MERGED"


pr_reviewers = Table(
    "pr_reviewers",
    Base.metadata,
    Column(
        "pr_id",
        ForeignKey("pull_requests.pull_request_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id", ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    ),
)


class Team(Base):
    __tablename__ = "teams"
    team_name = Column(String, primary_key=True)
    users = relationship("User", back_populates="team", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True)
    username = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    team_name = Column(String, ForeignKey("teams.team_name", ondelete="SET NULL"))
    team = relationship("Team", back_populates="users")
    assigned_prs = relationship(
        "PullRequest", secondary=pr_reviewers, back_populates="reviewers"
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"
    pull_request_id = Column(String, primary_key=True)
    pull_request_name = Column(String, nullable=False)
    author_id = Column(String, ForeignKey("users.user_id"))
    status = Column(SQLEnum(PRStatus), default=PRStatus.OPEN, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    merged_at = Column(DateTime(timezone=True), nullable=True)
    reviewers = relationship(
        "User", secondary=pr_reviewers, back_populates="assigned_prs"
    )
    author = relationship("User", foreign_keys=[author_id])


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class TeamMember(BaseModel):
    user_id: str
    username: str
    is_active: bool

    class Config:
        from_attributes = True


class TeamResponse(BaseModel):
    team_name: str
    members: List[TeamMember]


class TeamAddResponse(BaseModel):
    team: TeamResponse


class UserResponse(BaseModel):
    user_id: str
    username: str
    team_name: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class UserWrapper(BaseModel):
    user: UserResponse


class PullRequestSchema(BaseModel):
    pull_request_id: str
    pull_request_name: str
    author_id: str
    status: PRStatus
    assigned_reviewers: List[str] = []
    createdAt: Optional[datetime] = None
    mergedAt: Optional[datetime] = None

    class Config:
        from_attributes = True
        orm_mode = True

    @classmethod
    def from_orm(cls, obj):
        return cls(
            pull_request_id=obj.pull_request_id,
            pull_request_name=obj.pull_request_name,
            author_id=obj.author_id,
            status=obj.status,
            assigned_reviewers=[u.user_id for u in obj.reviewers],
            createdAt=obj.created_at,
            mergedAt=obj.merged_at,
        )


class PullRequestWrapper(BaseModel):
    pr: PullRequestSchema


class PullRequestShort(BaseModel):
    pull_request_id: str
    pull_request_name: str
    author_id: str
    status: PRStatus

    class Config:
        from_attributes = True


class ReassignResponse(BaseModel):
    pr: PullRequestSchema
    replaced_by: str


class UserReviewsResponse(BaseModel):
    user_id: str
    pull_requests: List[PullRequestShort]


class UserAssignmentStat(BaseModel):
    user_id: str
    assignments_count: int


class UserStatsResponse(BaseModel):
    stats: List[UserAssignmentStat]


class TeamDeactivationResponse(BaseModel):
    deactivated_count: int
    reassigned_prs: List[str]


class SetIsActiveRequest(BaseModel):
    user_id: str
    is_active: bool


class PullRequestCreateRequest(BaseModel):
    pull_request_id: str
    pull_request_name: str
    author_id: str


class TeamCreate(BaseModel):
    team_name: str
    members: List[TeamMember]


class MergeRequest(BaseModel):
    pull_request_id: str


class ReassignRequest(BaseModel):
    pull_request_id: str
    old_user_id: str = Field(alias="old_reviewer_id")

    class Config:
        allow_population_by_field_name = True


app = FastAPI(title="PR Reviewer Assignment Service (Test Task, Fall 2025)")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "INTERNAL_ERROR", "message": exc.detail}},
    )


def get_team(db: Session, team_name: str) -> Optional[Team]:
    return (
        db.query(Team)
        .options(joinedload(Team.users))
        .filter(Team.team_name == team_name)
        .first()
    )


def get_user(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.user_id == user_id).first()


def get_user_with_reviews(db: Session, user_id: str) -> Optional[User]:
    return (
        db.query(User)
        .options(selectinload(User.assigned_prs))
        .filter(User.user_id == user_id)
        .first()
    )


def get_pr(db: Session, pr_id: str) -> Optional[PullRequest]:
    return (
        db.query(PullRequest)
        .options(joinedload(PullRequest.reviewers))
        .filter(PullRequest.pull_request_id == pr_id)
        .first()
    )


@app.post(
    "/team/add", response_model=TeamAddResponse, status_code=status.HTTP_201_CREATED
)
def add_team(payload: TeamCreate, db: Session = Depends(get_db)):
    if get_team(db, payload.team_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {"code": "TEAM_EXISTS", "message": "team_name already exists"}
            },
        )

    team = Team(team_name=payload.team_name)
    db.add(team)

    members_objs = []
    for m in payload.members:
        user = get_user(db, m.user_id)
        if user:
            user.username = m.username
            user.is_active = m.is_active
            user.team_name = payload.team_name
        else:
            user = User(
                user_id=m.user_id,
                username=m.username,
                is_active=m.is_active,
                team_name=payload.team_name,
            )
            db.add(user)
        members_objs.append(user)

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "DB_ERROR",
                    "message": f"Database integrity error: {e}",
                }
            },
        )

    db.refresh(team)
    return {
        "team": TeamResponse(
            team_name=team.team_name,
            members=[TeamMember.from_orm(u) for u in members_objs],
        )
    }


@app.get("/team/get", response_model=TeamResponse)
def get_team_endpoint(team_name: str, db: Session = Depends(get_db)):
    team = get_team(db, team_name)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "resource not found"}},
        )
    return TeamResponse(
        team_name=team.team_name, members=[TeamMember.from_orm(u) for u in team.users]
    )


@app.post("/users/setIsActive", response_model=UserWrapper)
def set_is_active(req: SetIsActiveRequest, db: Session = Depends(get_db)):
    user = get_user(db, req.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "resource not found"}},
        )
    user.is_active = req.is_active
    db.commit()
    db.refresh(user)
    return {"user": UserResponse.from_orm(user)}


@app.get("/users/getReview", response_model=UserReviewsResponse)
def get_user_reviews(user_id: str, db: Session = Depends(get_db)):
    user = get_user_with_reviews(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "resource not found"}},
        )

    prs = [
        PullRequestShort.from_orm(pr)
        for pr in user.assigned_prs
        if pr.status == PRStatus.OPEN
    ]
    return UserReviewsResponse(user_id=user_id, pull_requests=prs)


@app.post(
    "/pullRequest/create",
    status_code=status.HTTP_201_CREATED,
    response_model=PullRequestWrapper,
)
def create_pr(req: PullRequestCreateRequest, db: Session = Depends(get_db)):

    if get_pr(db, req.pull_request_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "PR_EXISTS", "message": "PR id already exists"}},
        )
    author = (
        db.query(User)
        .options(joinedload(User.team))
        .filter(User.user_id == req.author_id)
        .first()
    )

    if not author or not author.team_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Author not found or not assigned to a team",
                }
            },
        )
    pr = PullRequest(
        pull_request_id=req.pull_request_id,
        pull_request_name=req.pull_request_name,
        author_id=req.author_id,
        status=PRStatus.OPEN,
        created_at=datetime.now(timezone.utc),
    )
    db.add(pr)
    candidates = (
        db.query(User)
        .filter(
            User.team_name == author.team_name,
            User.is_active,
            User.user_id != author.user_id,
        )
        .all()
    )
    random.shuffle(candidates)
    pr.reviewers = candidates[:2]
    db.commit()
    db.refresh(pr)
    resp = PullRequestSchema.from_orm(pr)
    return {"pr": resp}


@app.post("/pullRequest/merge", response_model=PullRequestWrapper)
def merge_pr(req: MergeRequest, db: Session = Depends(get_db)):
    pr = get_pr(db, req.pull_request_id)
    if not pr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "resource not found"}},
        )
    if pr.status != PRStatus.MERGED:
        pr.status = PRStatus.MERGED
        pr.merged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(pr)

    resp = PullRequestSchema.from_orm(pr)
    return {"pr": resp}


@app.post("/pullRequest/reassign", response_model=ReassignResponse)
def reassign_pr(req: ReassignRequest, db: Session = Depends(get_db)):
    pr = get_pr(db, req.pull_request_id)
    if not pr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "resource not found"}},
        )

    if pr.status == PRStatus.MERGED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "PR_MERGED",
                    "message": "cannot reassign on merged PR",
                }
            },
        )

    old_user = next((u for u in pr.reviewers if u.user_id == req.old_user_id), None)
    if not old_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "NOT_ASSIGNED",
                    "message": "reviewer is not assigned to this PR",
                }
            },
        )

    old_user_team = db.query(Team).filter(Team.team_name == old_user.team_name).first()
    if not old_user_team:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "NO_CANDIDATE",
                    "message": "Old reviewer is not in a team",
                }
            },
        )

    current_reviewer_ids = {u.user_id for u in pr.reviewers}
    candidates = (
        db.query(User)
        .filter(
            User.team_name == old_user_team.team_name,
            User.is_active,
            User.user_id.notin_(list(current_reviewer_ids)),
            User.user_id != pr.author_id,
        )
        .all()
    )
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "NO_CANDIDATE",
                    "message": "no active replacement candidate in team",
                }
            },
        )

    new_user = random.choice(candidates)
    pr.reviewers.remove(old_user)
    pr.reviewers.append(new_user)
    db.commit()
    db.refresh(pr)
    resp = PullRequestSchema.from_orm(pr)
    return ReassignResponse(pr=resp, replaced_by=new_user.user_id)


@app.get("/stats/user_assignments", response_model=UserStatsResponse)
def get_user_assignments_stats(db: Session = Depends(get_db)):
    results = (
        db.query(
            pr_reviewers.c.user_id,
            func.count(pr_reviewers.c.pr_id).label("assignments_count"),
        )
        .group_by(pr_reviewers.c.user_id)
        .all()
    )
    stats = [
        UserAssignmentStat(user_id=user_id, assignments_count=count)
        for user_id, count in results
    ]
    return UserStatsResponse(stats=stats)


@app.post("/team/deactivate_members", response_model=TeamDeactivationResponse)
def deactivate_members(team_name: str, db: Session = Depends(get_db)):
    team = get_team(db, team_name)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Team not found"}},
        )

    users_to_deactivate = [u for u in team.users if u.is_active]
    deactivating_user_ids = {u.user_id for u in users_to_deactivate}
    deactivated_count = len(users_to_deactivate)

    if not users_to_deactivate:
        return TeamDeactivationResponse(deactivated_count=0, reassigned_prs=[])
    open_prs_query = (
        db.query(PullRequest)
        .join(PullRequest.reviewers)
        .filter(
            PullRequest.status == PRStatus.OPEN, User.user_id.in_(deactivating_user_ids)
        )
        .options(selectinload(PullRequest.reviewers))
        .all()
    )

    reassigned_pr_ids = set()
    active_replacements_in_team = (
        db.query(User)
        .filter(
            User.team_name == team_name,
            User.is_active,
            User.user_id.notin_(deactivating_user_ids),
        )
        .all()
    )

    for pr in open_prs_query:
        current_reviewer_ids = {u.user_id for u in pr.reviewers}
        reviewers_to_replace = [
            u for u in pr.reviewers if u.user_id in deactivating_user_ids
        ]
        for old_user in reviewers_to_replace:
            valid_replacements = [
                r
                for r in active_replacements_in_team
                if r.user_id not in current_reviewer_ids and r.user_id != pr.author_id
            ]

            if valid_replacements:
                new_user = random.choice(valid_replacements)
                pr.reviewers.remove(old_user)
                pr.reviewers.append(new_user)
                current_reviewer_ids.add(new_user.user_id)
                reassigned_pr_ids.add(pr.pull_request_id)
            else:
                pr.reviewers.remove(old_user)
                reassigned_pr_ids.add(pr.pull_request_id)

    for user in users_to_deactivate:
        user.is_active = False

    db.commit()
    return TeamDeactivationResponse(
        deactivated_count=deactivated_count, reassigned_prs=list(reassigned_pr_ids)
    )


@app.post("/reset")
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return {"status": "reset_ok"}

"""Plan de tratamiento: objetivos del paciente y registros de avance.

Es información clínica: solo los profesionales con acceso activo al paciente (responsable
o colaboradores) ven, crean objetivos y registran avances. Administración y Recepción no.

Nada se reescribe: el texto de un objetivo es fijo y cada avance o cambio de estado queda
como un registro nuevo con autor y fecha (lo garantizan también disparadores de la base).
La auditoría registra las acciones sin copiar textos clínicos.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app import audit
from app.clinic_time import check_not_future
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.features import require_feature
from app.models import GoalStatus, GoalUpdate, TreatmentGoal, User
from app.permissions import CLINICAL_FORBIDDEN, get_clinical_patient
from app.schemas import GoalIn, GoalOut, GoalUpdateIn, GoalUpdateOut

router = APIRouter(prefix="/api", tags=["plan de tratamiento"],
                   dependencies=[Depends(require_feature("objetivos"))])

_GOAL_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Objetivo no encontrado.")


def _goals_out(db: Session, user: CurrentUser, goals: list[TreatmentGoal]) -> list[GoalOut]:
    if not goals:
        return []
    ids = [g.id for g in goals]
    creators = dict(db.execute(select(User.id, User.full_name).where(
        User.clinic_id == user.clinic_id, User.id.in_({g.created_by for g in goals}))).all())
    author = aliased(User)
    rows = db.execute(
        select(GoalUpdate, author.full_name)
        .join(author, (author.id == GoalUpdate.author_id) & (author.clinic_id == GoalUpdate.clinic_id))
        .where(GoalUpdate.clinic_id == user.clinic_id, GoalUpdate.goal_id.in_(ids))
        .order_by(GoalUpdate.created_at.desc())
    ).all()
    updates: dict[uuid.UUID, list[GoalUpdateOut]] = {}
    for u, name in rows:
        updates.setdefault(u.goal_id, []).append(GoalUpdateOut(
            id=u.id, author_name=name, session_date=u.session_date, progress=u.progress,
            new_status=u.new_status, note=u.note, created_at=u.created_at))
    return [
        GoalOut(id=g.id, area=g.area, description=g.description, target_date=g.target_date,
                status=g.status, progress=g.progress, created_by_name=creators.get(g.created_by, ""),
                created_at=g.created_at, updates=updates.get(g.id, []))
        for g in goals
    ]


@router.get("/patients/{patient_id}/goals", response_model=list[GoalOut])
def list_goals(patient_id: uuid.UUID, request: Request,
               user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    patient, _ = get_clinical_patient(db, user, patient_id)
    goals = db.scalars(
        select(TreatmentGoal)
        .where(TreatmentGoal.clinic_id == user.clinic_id, TreatmentGoal.patient_id == patient.id)
        .order_by(TreatmentGoal.created_at)
    ).all()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="goal.list",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details={"count": len(goals)}, request=request)
    db.commit()
    return _goals_out(db, user, list(goals))


@router.post("/patients/{patient_id}/goals", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(patient_id: uuid.UUID, payload: GoalIn, request: Request,
                user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    patient, _ = get_clinical_patient(db, user, patient_id)
    goal = TreatmentGoal(clinic_id=user.clinic_id, patient_id=patient.id, created_by=user.id,
                         area=payload.area, description=payload.description,
                         target_date=payload.target_date, status=GoalStatus.active.value, progress=0)
    db.add(goal)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="goal.create",
                 entity_type="goal", entity_id=goal.id, patient_id=patient.id, request=request)
    db.commit()
    return _goals_out(db, user, [goal])[0]


@router.post("/goals/{goal_id}/updates", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def add_goal_update(goal_id: uuid.UUID, payload: GoalUpdateIn, request: Request,
                    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Registra un avance (porcentaje + nota) y, si corresponde, un cambio de estado."""
    if not user.is_professional:
        raise CLINICAL_FORBIDDEN
    goal = db.scalar(select(TreatmentGoal).where(TreatmentGoal.id == goal_id,
                                                 TreatmentGoal.clinic_id == user.clinic_id))
    if goal is None:
        raise _GOAL_NOT_FOUND
    try:
        get_clinical_patient(db, user, goal.patient_id)
    except HTTPException:
        raise _GOAL_NOT_FOUND from None

    new_status = payload.new_status.value if payload.new_status else None
    if new_status == goal.status:
        new_status = None
    if goal.status != GoalStatus.active.value and new_status != GoalStatus.active.value:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El objetivo está cerrado. Para registrar avances, reabrilo (estado En curso).")
    check_not_future(db, user.clinic_id, payload.session_date)
    progress = payload.progress
    if new_status == GoalStatus.achieved.value:
        progress = 100  # un objetivo logrado está al 100 %
    elif progress is None:
        progress = goal.progress
    update = GoalUpdate(clinic_id=user.clinic_id, goal_id=goal.id, author_id=user.id,
                        session_date=payload.session_date, progress=progress, new_status=new_status,
                        note=payload.note)
    db.add(update)
    goal.progress = progress
    if new_status:
        goal.status = new_status
    details = {"status": new_status} if new_status else {}
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="goal.update",
                 entity_type="goal", entity_id=goal.id, patient_id=goal.patient_id,
                 details=details, request=request)
    db.commit()
    return _goals_out(db, user, [goal])[0]

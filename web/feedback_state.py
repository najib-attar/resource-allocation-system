"""Audit authorized maintenance in active reports using the existing transaction."""
from datetime import datetime, timezone
import hashlib
import uuid
from sqlalchemy import select
from .feedback_access import managed_scope
from .notification_service import publish_event
from .persistence.models import EquipmentReservation, FeedbackEvent, ResourceFeedback


def record_resource_action(session, kind, resource_id, actor, message):
    query = select(ResourceFeedback).where(ResourceFeedback.status.in_(['Submitted','Under Review']), managed_scope(actor))
    if kind == 'room':
        query = query.where(ResourceFeedback.room_resource_id == resource_id)
    else:
        query = query.join(EquipmentReservation, EquipmentReservation.id == ResourceFeedback.equipment_reservation_id).where(EquipmentReservation.unit_id == resource_id)
    for report in session.scalars(query.order_by(ResourceFeedback.id).with_for_update(of=ResourceFeedback)):
        report.revision += 1
        report.updated_at = datetime.now(timezone.utc)
        publish_event(session, FeedbackEvent(report_id=report.id, actor_id=actor, revision=report.revision,
            status=report.status, message='Authorized resource action: '+message, action_key=uuid.uuid4().hex,
            fingerprint=hashlib.sha256(message.encode('utf-8')).hexdigest()), recipient_ids={report.reporter_id}, notify_actor=True)

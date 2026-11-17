from fastapi import APIRouter

from app.api.v1 import analytics, appointments, auth, clinic_admin, clinics, notifications, platform, queue, realtime, simulation

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(clinics.router)
api_router.include_router(clinic_admin.router)
api_router.include_router(appointments.router)
api_router.include_router(queue.router)
api_router.include_router(analytics.router)
api_router.include_router(notifications.router)
api_router.include_router(realtime.router)
api_router.include_router(simulation.router)
api_router.include_router(platform.router)

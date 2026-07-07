from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RequestOut(BaseModel):
    id: int = Field(description="Unique identifier of the media request")
    plex_user_id: str = Field(description="Plex User ID of the requester")
    plex_user: Optional[str] = Field(description="Name of the Plex requester")
    title: str = Field(description="Title of the media requested")
    year: Optional[int] = Field(description="Release year of the media")
    media_type: str = Field(description="Type of media: movie or show")
    status: str = Field(description="Current status of the request (pending, sent_to_arr, available, failed)")
    requested_at: Optional[datetime] = Field(description="Timestamp when the media was requested")
    available_at: Optional[datetime] = Field(description="Timestamp when the media became available")
    poster_url: Optional[str] = Field(description="URL of the media poster image")
    overview: Optional[str] = Field(description="Overview/synopsis of the media")
    arr_instance_id: Optional[int] = Field(description="ID of the ArrInstance that processed this request")


class UserOut(BaseModel):
    id: int = Field(description="Unique identifier of the user in Plexarr")
    plex_user_id: str = Field(description="Plex User ID")
    display_name: Optional[str] = Field(description="Display name of the Plex user")
    plex_email: Optional[str] = Field(description="Plex account email address")
    notification_email: Optional[str] = Field(description="Email address where notifications are sent")
    enabled: bool = Field(description="Whether the user is currently enabled and monitored")
    notify_admin: bool = Field(description="Whether admin notifications are triggered for this user")
    notify_on_request: Optional[bool] = Field(description="Send email on media request")
    notify_on_available: Optional[bool] = Field(description="Send email when media is available")
    created_at: Optional[datetime] = Field(description="Timestamp when the user was created")
    sonarr_instance_id: Optional[int] = Field(description="Routed Sonarr ArrInstance ID")
    radarr_instance_id: Optional[int] = Field(description="Routed Radarr ArrInstance ID")


class HealthServiceOut(BaseModel):
    ok: Optional[bool] = Field(description="Health status of the service")
    message: str = Field(description="Status message or error info")
    response_ms: Optional[float] = Field(description="Response latency of the service in milliseconds")


class HealthOut(BaseModel):
    status: str = Field(description="Overall health status of the application")
    checked_at: str = Field(description="ISO 8601 timestamp of the health check execution")
    services: dict[str, HealthServiceOut] = Field(description="Map of individual service statuses")


class MetricsOut(BaseModel):
    runtime: dict = Field(description="Runtime metrics (memory, requests, etc.)")
    db: dict = Field(description="Database aggregate metrics")


class PollHistoryOut(BaseModel):
    id: int = Field(description="Unique identifier of the poll run")
    job: str = Field(description="Scheduler job name (watchlist or arr_status)")
    started_at: datetime = Field(description="Timestamp when the poll run started")
    duration_ms: Optional[int] = Field(description="Duration of the poll run in milliseconds")
    items_processed: int = Field(description="Number of items analyzed during the run")
    new_requests: int = Field(description="Number of new requests created or retried")
    newly_available: int = Field(description="Number of requests transitioned to available")
    errors: int = Field(description="Number of errors encountered during the run")
    error_detail: Optional[str] = Field(description="Error message if the run failed")

"""Story 5.1 / 14.2 / 15.2 / 15.4: AI provider configuration router.

API endpoints for configuring AI provider with API key management.
Supports 5 provider types: claude_api, openai_api, claude_subscription,
chatgpt_subscription, and openai_compatible.

Story 15.2: Subscription auth endpoints for sidecar token management.
Story 15.4: Subscription configure endpoint (no API key needed).
"""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.core.encryption import decrypt_credential, encrypt_credential
from src.database import get_db
from src.logging_config import get_logger
from src.models.ai_provider import AIProviderConfig, AIProviderStatus
from src.schemas.ai_provider import (
    SIDECAR_PROVIDER_MAP,
    AIChatRequest,
    AIChatResponse,
    AIProviderConfigRequest,
    AIProviderConfigResponse,
    AIProviderDeleteResponse,
    AIProviderTestResponse,
    SubscriptionAuthRevokeRequest,
    SubscriptionAuthStartRequest,
    SubscriptionAuthStartResponse,
    SubscriptionAuthStatusResponse,
    SubscriptionAuthTokenRequest,
    SubscriptionAuthTokenResponse,
    SubscriptionConfigureRequest,
)
from src.schemas.auth import ErrorResponse
from src.services.ai_provider import mask_api_key, validate_ai_api_key
from src.services.sidecar import (
    get_sidecar_auth_status,
    get_sidecar_health,
    revoke_sidecar_auth,
    start_sidecar_auth,
    submit_sidecar_token,
    validate_sidecar_connection,
)
from src.services.telegram_chat import handle_chat_web

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _build_response(
    config: AIProviderConfig, masked_key: str
) -> AIProviderConfigResponse:
    """Build an API response from an AIProviderConfig model instance.

    Args:
        config: The database model instance.
        masked_key: Pre-masked API key string for safe display.

    Returns:
        Populated response schema.
    """
    return AIProviderConfigResponse(
        provider_type=config.provider_type,
        status=config.status,
        model_name=config.model_name,
        base_url=config.base_url,
        sidecar_provider=config.sidecar_provider,
        masked_api_key=masked_key,
        last_validated_at=config.last_validated_at,
        last_error=config.last_error,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get(
    "/provider",
    response_model=AIProviderConfigResponse,
    responses={
        200: {"description": "Current AI provider configuration"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "No AI provider configured"},
    },
)
async def get_ai_provider(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AIProviderConfigResponse:
    """Get the current AI provider configuration.

    Returns provider type, status, and masked API key.
    """
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No AI provider configured",
        )

    if config.encrypted_api_key:
        decrypted_key = decrypt_credential(config.encrypted_api_key)
        masked = mask_api_key(decrypted_key)
    else:
        # Subscription types using sidecar OAuth have no stored API key
        masked = "sidecar-managed"

    return _build_response(config, masked)


@router.post(
    "/provider",
    response_model=AIProviderConfigResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "AI provider configured successfully"},
        400: {"model": ErrorResponse, "description": "Invalid API key"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def configure_ai_provider(
    request: AIProviderConfigRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AIProviderConfigResponse:
    """Configure AI provider with API key.

    Validates the API key, encrypts it, and stores the configuration.
    If a provider is already configured, it is updated.
    """
    # Validate the API key (run in thread to avoid blocking event loop)
    is_valid, error_message = await asyncio.to_thread(
        validate_ai_api_key,
        request.provider_type,
        request.api_key,
        base_url=request.base_url,
        model_name=request.model_name,
    )

    if not is_valid:
        logger.warning(
            "AI provider configuration failed",
            user_id=str(current_user.id),
            provider=request.provider_type.value,
            error=error_message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Check if configuration already exists
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == current_user.id)
    )
    existing = result.scalar_one_or_none()

    now = datetime.now(UTC)

    if existing:
        # Update existing configuration
        existing.provider_type = request.provider_type
        existing.encrypted_api_key = encrypt_credential(request.api_key)
        existing.model_name = request.model_name
        existing.base_url = request.base_url
        existing.sidecar_provider = None  # Clear stale sidecar state on reconfigure
        existing.status = AIProviderStatus.CONNECTED
        existing.last_validated_at = now
        existing.last_error = None
        existing.updated_at = now
        config = existing
    else:
        # Create new configuration
        config = AIProviderConfig(
            user_id=current_user.id,
            provider_type=request.provider_type,
            encrypted_api_key=encrypt_credential(request.api_key),
            model_name=request.model_name,
            base_url=request.base_url,
            status=AIProviderStatus.CONNECTED,
            last_validated_at=now,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)

    logger.info(
        "AI provider configured successfully",
        user_id=str(current_user.id),
        provider=request.provider_type.value,
    )

    masked = mask_api_key(request.api_key)
    return _build_response(config, masked)


@router.delete(
    "/provider",
    response_model=AIProviderDeleteResponse,
    responses={
        200: {"description": "AI provider configuration removed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "No AI provider configured"},
    },
)
async def delete_ai_provider(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AIProviderDeleteResponse:
    """Remove AI provider configuration.

    Deletes the stored API key and provider settings.
    """
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No AI provider configured",
        )

    # Revoke sidecar auth if this was a sidecar-managed provider
    if config.sidecar_provider:
        revoke_result = await revoke_sidecar_auth(config.sidecar_provider)
        if revoke_result is None:
            logger.warning(
                "Sidecar auth revocation failed during provider deletion (sidecar unreachable)",
                user_id=str(current_user.id),
                sidecar_provider=config.sidecar_provider,
            )

    await db.delete(config)
    await db.commit()

    logger.info(
        "AI provider configuration removed",
        user_id=str(current_user.id),
    )

    return AIProviderDeleteResponse(
        message="AI provider configuration removed successfully"
    )


@router.post(
    "/provider/test",
    response_model=AIProviderTestResponse,
    responses={
        200: {"description": "API key test result"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "No AI provider configured"},
    },
)
async def test_ai_provider(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AIProviderTestResponse:
    """Test the stored AI provider API key.

    Decrypts the stored key and makes a validation request to the provider.
    """
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No AI provider configured",
        )

    # Subscription types using sidecar OAuth have no stored API key;
    # validate by checking sidecar health + auth status instead.
    if not config.encrypted_api_key:
        if config.sidecar_provider:
            is_valid, error_message = await validate_sidecar_connection(
                config.sidecar_provider
            )
            now = datetime.now(UTC)
            if is_valid:
                config.status = AIProviderStatus.CONNECTED
                config.last_validated_at = now
                config.last_error = None
                config.updated_at = now
                await db.commit()
                return AIProviderTestResponse(
                    success=True,
                    message="Sidecar connection verified successfully.",
                )
            else:
                config.status = AIProviderStatus.ERROR
                config.last_error = error_message
                config.updated_at = now
                await db.commit()
                return AIProviderTestResponse(
                    success=False,
                    message=error_message or "Sidecar validation failed",
                )
        now = datetime.now(UTC)
        config.status = AIProviderStatus.ERROR
        config.last_error = "No API key and no sidecar configuration"
        config.updated_at = now
        await db.commit()
        return AIProviderTestResponse(
            success=False,
            message="Provider has no API key and no sidecar configuration. "
            "Please reconfigure your AI provider.",
        )

    # Decrypt and test the key (run in thread to avoid blocking event loop)
    decrypted_key = decrypt_credential(config.encrypted_api_key)
    is_valid, error_message = await asyncio.to_thread(
        validate_ai_api_key,
        config.provider_type,
        decrypted_key,
        base_url=config.base_url,
        model_name=config.model_name,
    )

    now = datetime.now(UTC)

    if is_valid:
        config.status = AIProviderStatus.CONNECTED
        config.last_validated_at = now
        config.last_error = None
        config.updated_at = now
        await db.commit()

        return AIProviderTestResponse(
            success=True,
            message="AI provider configured successfully",
        )
    else:
        config.status = AIProviderStatus.ERROR
        config.last_error = error_message
        config.updated_at = now
        await db.commit()

        return AIProviderTestResponse(
            success=False,
            message=error_message or "API key validation failed",
        )


@router.post(
    "/chat",
    response_model=AIChatResponse,
    responses={
        200: {"description": "AI chat response"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "No AI provider configured"},
        502: {"model": ErrorResponse, "description": "AI provider error"},
    },
)
async def ai_chat(
    request: AIChatRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AIChatResponse:
    """Send a message to the AI with glucose context.

    Uses the user's configured AI provider and recent glucose data
    to generate a contextual response.
    """
    chat_result = await handle_chat_web(db, current_user.id, request.message)

    return AIChatResponse(
        response=chat_result.content,
        disclaimer="Not medical advice. Consult your healthcare provider.",
        conversation_id=str(chat_result.conversation_id),
        message_id=str(chat_result.assistant_message_id)
        if chat_result.assistant_message_id
        else None,
    )


# ── Story 35.3: Chat History Endpoints ──


@router.get(
    "/chat/history",
    responses={
        200: {"description": "Chat history for current conversation"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_chat_history(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Get chat history for the user's most recent conversation."""
    from src.models.chat_message import ChatMessage
    from src.services.chat_history import get_conversation_messages

    # Find the most recent conversation that has messages (not phantom)
    result = await db.execute(
        select(ChatMessage.conversation_id)
        .where(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return {"conversation_id": None, "messages": [], "total": 0}

    conversation_id = row[0]
    messages, total = await get_conversation_messages(
        db, current_user.id, conversation_id, limit=limit, offset=offset
    )

    return {
        "conversation_id": str(conversation_id),
        "messages": [
            {
                "id": str(msg.id),
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
                "model": msg.model,
                "disclaimer": (
                    "Not medical advice. Consult your healthcare provider."
                    if msg.role.value == "assistant"
                    else None
                ),
            }
            for msg in messages
        ],
        "total": total,
    }


@router.delete(
    "/chat/history",
    responses={
        200: {"description": "Chat history cleared"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def delete_chat_history(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Clear the user's chat history. Starts a fresh conversation."""
    from src.services.chat_history import clear_conversation

    deleted = await clear_conversation(db, current_user.id)
    await db.commit()

    return {"message": "Chat history cleared", "deleted": deleted}


# ── Story 15.4: Subscription Configure Endpoint ──


@router.post(
    "/subscription/configure",
    response_model=AIProviderConfigResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Subscription provider configured via sidecar"},
        400: {"model": ErrorResponse, "description": "Sidecar not authenticated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        502: {"model": ErrorResponse, "description": "Sidecar unreachable"},
    },
)
async def configure_subscription_provider(
    request: SubscriptionConfigureRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AIProviderConfigResponse:
    """Configure a subscription provider via the managed sidecar.

    No API key or base_url required. The sidecar handles authentication
    and the API auto-populates the base_url from AI_SIDECAR_URL.
    Requires the sidecar to be running and authenticated for the provider.
    """
    provider_type = SIDECAR_PROVIDER_MAP[request.sidecar_provider]

    # Validate sidecar is healthy and authenticated
    is_valid, error_message = await validate_sidecar_connection(
        request.sidecar_provider
    )
    if not is_valid:
        logger.warning(
            "Subscription provider configuration failed",
            user_id=str(current_user.id),
            provider=request.sidecar_provider,
            provider_type=provider_type.value,
            error=error_message,
        )
        # Distinguish between sidecar unreachable (502) vs other errors (400)
        error_msg = error_message or "Sidecar validation failed"
        is_unreachable = "not reachable" in error_msg
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY
            if is_unreachable
            else status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Check if configuration already exists
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == current_user.id)
    )
    existing = result.scalar_one_or_none()

    now = datetime.now(UTC)

    if existing:
        existing.provider_type = provider_type
        existing.encrypted_api_key = None  # Sidecar handles auth
        existing.model_name = request.model_name
        existing.base_url = None  # Auto-routed via AI_SIDECAR_URL
        existing.sidecar_provider = request.sidecar_provider
        existing.status = AIProviderStatus.CONNECTED
        existing.last_validated_at = now
        existing.last_error = None
        existing.updated_at = now
        config = existing
    else:
        config = AIProviderConfig(
            user_id=current_user.id,
            provider_type=provider_type,
            encrypted_api_key=None,
            model_name=request.model_name,
            base_url=None,
            sidecar_provider=request.sidecar_provider,
            status=AIProviderStatus.CONNECTED,
            last_validated_at=now,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)

    logger.info(
        "Subscription provider configured via sidecar",
        user_id=str(current_user.id),
        provider=request.sidecar_provider,
        provider_type=provider_type.value,
    )

    return _build_response(config, "sidecar-managed")


# ── Story 15.2: Subscription Auth Endpoints ──


@router.get(
    "/subscription/auth/status",
    response_model=SubscriptionAuthStatusResponse,
    responses={
        200: {"description": "Current sidecar auth status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def subscription_auth_status(
    _current_user: DiabeticOrAdminUser,
) -> SubscriptionAuthStatusResponse:
    """Check the sidecar's current authentication state.

    Returns whether the sidecar is reachable and each provider's
    auth status.
    """
    auth_data = await get_sidecar_auth_status()

    if auth_data is None:
        return SubscriptionAuthStatusResponse(sidecar_available=False)

    return SubscriptionAuthStatusResponse(
        sidecar_available=True,
        claude=auth_data.get("claude"),
        codex=auth_data.get("codex"),
    )


@router.post(
    "/subscription/auth/start",
    response_model=SubscriptionAuthStartResponse,
    responses={
        200: {"description": "Auth method info"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        502: {"model": ErrorResponse, "description": "Sidecar unreachable"},
    },
)
async def subscription_auth_start(
    request: SubscriptionAuthStartRequest,
    _current_user: DiabeticOrAdminUser,
) -> SubscriptionAuthStartResponse:
    """Start the auth flow for a subscription provider.

    Returns instructions for how to obtain and submit a token.
    """
    result = await start_sidecar_auth(request.provider)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI sidecar is not reachable. Ensure the sidecar container is running.",
        )

    return SubscriptionAuthStartResponse(
        provider=result["provider"],
        auth_method=result.get("auth_method", "token_paste"),
        instructions=result.get("instructions", ""),
    )


@router.post(
    "/subscription/auth/token",
    response_model=SubscriptionAuthTokenResponse,
    responses={
        200: {"description": "Token submission result"},
        400: {"model": ErrorResponse, "description": "Invalid token"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        502: {"model": ErrorResponse, "description": "Sidecar unreachable"},
    },
)
async def subscription_auth_token(
    request: SubscriptionAuthTokenRequest,
    _current_user: DiabeticOrAdminUser,
) -> SubscriptionAuthTokenResponse:
    """Submit an OAuth token to the sidecar for storage.

    The user obtains the token by running the provider's CLI on their
    host machine, then pastes it into the settings UI.
    """
    result = await submit_sidecar_token(request.provider, request.token)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI sidecar is not reachable. Ensure the sidecar container is running.",
        )

    if not result.get("success", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to store token"),
        )

    return SubscriptionAuthTokenResponse(
        success=True,
        provider=request.provider,
    )


@router.post(
    "/subscription/auth/revoke",
    responses={
        200: {"description": "Auth revoked"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        502: {"model": ErrorResponse, "description": "Sidecar unreachable"},
    },
)
async def subscription_auth_revoke(
    request: SubscriptionAuthRevokeRequest,
    _current_user: DiabeticOrAdminUser,
) -> dict:
    """Revoke the stored token for a subscription provider."""
    result = await revoke_sidecar_auth(request.provider)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI sidecar is not reachable. Ensure the sidecar container is running.",
        )

    return {"revoked": True, "provider": request.provider}


@router.get(
    "/subscription/sidecar/health",
    responses={
        200: {"description": "Sidecar health status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def subscription_sidecar_health(
    _current_user: DiabeticOrAdminUser,
) -> dict:
    """Check if the AI sidecar container is healthy."""
    health = await get_sidecar_health()

    if health is None:
        return {"available": False, "status": "unreachable"}

    return {
        "available": True,
        "status": health.get("status", "unknown"),
        "claude_auth": health.get("claude_auth", False),
        "codex_auth": health.get("codex_auth", False),
    }

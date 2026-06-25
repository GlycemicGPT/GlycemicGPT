package com.glycemicgpt.mobile.data.meal

/**
 * Typed failures for the Meal Intelligence APIs, so ViewModels can render the right UI state
 * (feature-off degradation, vision-unavailable message, etc.) instead of a generic error.
 */
sealed class MealException(message: String) : Exception(message) {

    /** The meal_intelligence feature flag is off (backend returns 404 for the whole surface). */
    class FeatureDisabled(message: String = "Meal intelligence is not enabled.") :
        MealException(message)

    /** The user's AI provider has no vision route (backend returns 422 vision_unavailable). */
    class VisionUnavailable(
        message: String = "Vision is not available on your current AI provider.",
    ) : MealException(message)

    /** No AI provider is configured for this user (backend returns 404). */
    class NoAiProvider(message: String = "No AI provider configured.") : MealException(message)

    /** The image exceeded the server's size cap (413). */
    class ImageTooLarge(message: String = "That photo is too large. Try a smaller image.") :
        MealException(message)

    /** The image was not a supported format (415). */
    class UnsupportedImage(
        message: String = "Unsupported image type. Use a JPEG, PNG, or WebP photo.",
    ) : MealException(message)

    /** The estimate could not be produced or was out of range (400/422, non-vision). */
    class EstimateFailed(message: String) : MealException(message)

    /** Too many uploads in a short window (429). */
    class RateLimited(message: String = "Too many photos at once. Please wait a moment.") :
        MealException(message)

    /** The record or common food was not found, or is owned by another user (404). */
    class NotFound(message: String = "That item could not be found.") : MealException(message)

    /** A common-food name collided with an existing one (409). */
    class NameConflict(message: String = "A common food with that name already exists.") :
        MealException(message)

    /** A submitted carb value or name failed validation (422). */
    class Validation(message: String) : MealException(message)
}

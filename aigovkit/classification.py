from aigovkit.models import ClassificationInput, ClassificationSuggestion


def suggest_classification(metadata: ClassificationInput) -> ClassificationSuggestion:
    if metadata.contains_credentials_or_regulated_sensitive_data:
        return ClassificationSuggestion(
            classification="restricted",
            reason="Declared credentials or regulated sensitive data take precedence.",
        )
    if metadata.contains_personal_data or metadata.contains_confidential_business_data:
        return ClassificationSuggestion(
            classification="confidential",
            reason="Declared personal data or confidential business data requires protection.",
        )
    if metadata.approved_for_public_release:
        return ClassificationSuggestion(
            classification="public",
            reason="Public release is declared and no sensitivity flags apply.",
        )
    return ClassificationSuggestion(
        classification="internal", reason="Public release has not been approved."
    )

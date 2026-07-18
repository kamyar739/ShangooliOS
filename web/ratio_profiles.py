RATIO_PROFILES = {
    "horizontal": {
        "master_ratio": "3:2",
        "required_ratios": ("3:2", "4:3", "5:4", "14:11"),
    },
    "vertical": {
        "master_ratio": "2:3",
        "required_ratios": ("2:3", "3:4", "4:5", "11:14"),
    },
    "square": {
        "master_ratio": "1:1",
        "required_ratios": ("1:1",),
    },
}


def get_ratio_profile(orientation: str) -> dict:
    normalized = orientation.strip().lower()
    try:
        return RATIO_PROFILES[normalized]
    except KeyError as error:
        valid = ", ".join(RATIO_PROFILES)
        raise ValueError(
            f"Unsupported orientation '{orientation}'. Expected one of: {valid}."
        ) from error

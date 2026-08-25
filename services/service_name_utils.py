import re


def normalize_service(name: str) -> str:
    """Normalisasi nama service menjadi bentuk lowercase underscore."""
    return name.lower().strip().replace("-", "_").replace(" ", "_")


def service_name_variants(name: str) -> list:
    """
    Hasilkan varian nama service yang umum di label Prometheus/Tempo/K8s.
    Mis. 'payment_gateway_prod' → ['payment_gateway_prod', 'payment-gateway-prod',
    'payment_gateway_prod_apps', 'payment-gateway-prod-apps'].
    """
    base = normalize_service(name)
    variants = {base}

    hyphen = base.replace("_", "-")
    variants.add(hyphen)

    if not base.endswith("_apps"):
        variants.add(f"{base}_apps")
        variants.add(f"{hyphen}-apps")

    return sorted(variants)


def build_label_regex(name: str) -> str:
    """
    Regex untuk mencocokkan label yang berisi nama service dalam berbagai bentuk.
    Contoh: 'payment_gateway_prod' → 'payment[_-]gateway[_-]prod([_-]apps)?'
    """
    parts = normalize_service(name).split("_")
    core = "[_-]".join(re.escape(p) for p in parts)
    return f"{core}([_-]apps)?"


def matches_service(label_value: str, name: str) -> bool:
    """True bila label_value mengandung salah satu varian nama service."""
    if not label_value:
        return False
    val = label_value.lower()
    return any(v in val for v in service_name_variants(name))

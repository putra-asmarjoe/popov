import re
from typing import Iterable, Optional


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


# ── Canonical resolve (Fix #246): raw devops → service library kanonik ─────────

# Suffix/prefix umum yang ditambahkan deployment/devops ke nama service.
# Di-strip saat canonicalize — "lovvit-release-coupon-apps" → "lovvit-release-coupon".
_AFFIX_SUFFIXES = ("-apps", "_apps", "-api", "-service", "-svc", "-backend", "-frontend", "-worker")
_AFFIX_PREFIXES = ("prod-", "production-", "staging-", "stage-", "dev-", "development-", "test-", "old-", "legacy-")


def _strip_env_affixes(name: str) -> str:
    """Buang affix environment/deployment berulang dari nama service.

    'prod-lovvit-release-coupon-apps-v2' → 'lovvit-release-coupon-v2'.
    Hanya affix yang TIDAK mengubah identitas inti — dipakai sebagai kandidat
    sebelum dicocokkan ke library (library tetap sumber kebenaran).
    """
    out = name.strip()
    changed = True
    while changed:
        changed = False
        for suf in _AFFIX_SUFFIXES:
            if out.lower().endswith(suf) and len(out) > len(suf) + 1:
                out = out[: -len(suf)]
                changed = True
                break
        if not changed:
            for pre in _AFFIX_PREFIXES:
                if out.lower().startswith(pre) and len(out) > len(pre) + 1:
                    out = out[len(pre):]
                    changed = True
                    break
    return out


def canonical_service(raw: str, library_ids) -> Optional[str]:
    """Resolve nama service mentah (dari alert/devops/manual) ke serviceId KANONIK
    di service library, bila ada kecocokan kuat.

    Urutan:
      1. raw persis (case beda / dash-underscore) ada di library
      2. raw sudah di-strip affix env (apps/api/service/prod-...) cocok persis
      3. salah satu library adalah substring raw ATAU raw substring library
         (setelah strip affix) — cegah false-positive dgn panjang minimal.

    Return serviceId library (str) atau None. library_ids: iterable serviceId.
    """
    if not raw or not library_ids:
        return None
    libs = {str(x).strip() for x in library_ids if str(x).strip()}
    raw_s = str(raw).strip()
    if not raw_s or raw_s in ("unknown", "-", "null", "none"):
        return None

    # 1. exact (normalisasi dash/underscore + case)
    norm = normalize_service(raw_s)
    for lib in libs:
        if normalize_service(lib) == norm:
            return lib

    # 2. strip affix → exact
    stripped = _strip_env_affixes(raw_s)
    norm_stripped = normalize_service(stripped)
    for lib in libs:
        if normalize_service(lib) == norm_stripped:
            return lib

    # 3. substring (arah dua) setelah strip affix — minimal 3 token agar aman
    parts = [p for p in re.split(r"[^a-z0-9]+", norm_stripped) if p]
    if len(parts) < 3:
        return None
    for lib in sorted(libs, key=len, reverse=True):
        lib_norm = normalize_service(lib)
        if lib_norm in norm_stripped or norm_stripped in lib_norm:
            return lib
    return None

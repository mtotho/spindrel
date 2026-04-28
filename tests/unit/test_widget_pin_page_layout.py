from __future__ import annotations

from pathlib import Path


PAGE = Path(__file__).resolve().parents[2] / "ui/app/(app)/widgets/pins/[pinId].tsx"


def test_full_pinned_widget_page_does_not_cap_desktop_height() -> None:
    source = PAGE.read_text()

    assert "md:h-[min(780px,calc(100vh-170px))]" not in source
    assert "md:flex-none" not in source
    assert (
        'className="mx-auto flex min-h-0 w-full flex-1 flex-col md:max-w-[1180px]"'
        in source
    )

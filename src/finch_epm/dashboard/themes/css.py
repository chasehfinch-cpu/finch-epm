"""CSS generation from theme tokens.

Converts a ThemeTokens instance into CSS custom properties and handles
scoped injection of user custom_css.
"""

from __future__ import annotations

from finch_epm.dashboard.themes.tokens import ThemeTokens


def tokens_to_css(tokens: ThemeTokens) -> str:
    """Generate a complete CSS block from theme tokens.

    Returns CSS that sets custom properties on ``.fdash-root`` and
    includes P&L hierarchy row classes.
    """
    css_vars = tokens.to_css_vars()
    lines = [".fdash-root {"]
    for prop, value in css_vars.items():
        lines.append(f"  {prop}: {value};")
    lines.append("}")
    lines.append("")

    # P&L hierarchy level classes
    for level_name, level_attr in [
        ("row-level5", tokens.pl_level5),
        ("row-level4", tokens.pl_level4),
        ("row-level3", tokens.pl_level3),
        ("row-level2", tokens.pl_level2),
        ("row-level1", tokens.pl_level1),
        ("row-ebitda", tokens.pl_ebitda),
        ("row-netincome", tokens.pl_net_income),
        ("row-stats-header", tokens.pl_stats_header),
    ]:
        lines.append(f".fdash-root .{level_name} {{")
        lines.append(f"  background-color: {level_attr.bg};")
        lines.append(f"  color: {level_attr.text};")
        lines.append(f"  font-weight: {level_attr.weight};")
        if level_attr.size:
            lines.append(f"  font-size: {level_attr.size};")
        lines.append("}")

        # Sticky account column inherits row bg
        lines.append(f".fdash-root .{level_name} td.col-account {{")
        lines.append(f"  background-color: {level_attr.bg};")
        lines.append(f"  color: {level_attr.text};")
        lines.append("}")

        # Variance text on dark backgrounds should be white
        if level_attr.text == "#ffffff":
            lines.append(f".fdash-root .{level_name} .col-variance-fav,")
            lines.append(f".fdash-root .{level_name} .col-variance-unfav {{")
            lines.append("  color: #fff;")
            lines.append("}")

        lines.append("")

    return "\n".join(lines)


def scope_custom_css(custom_css: str) -> str:
    """Scope user custom CSS under ``.fdash-root``.

    Prepends ``.fdash-root`` to every selector so user styles cannot
    leak outside the dashboard container. Uses basic CSS parsing --
    handles most common selector patterns.

    Args:
        custom_css: Raw CSS string from the .fdash ``custom_css`` field.

    Returns:
        Scoped CSS string.
    """
    if not custom_css or not custom_css.strip():
        return ""

    # Try to use tinycss2 if available for robust parsing
    try:
        return _scope_with_tinycss2(custom_css)
    except ImportError:
        return _scope_basic(custom_css)


def _scope_with_tinycss2(custom_css: str) -> str:
    """Scope CSS using tinycss2 parser."""
    import tinycss2

    tokens = tinycss2.parse_stylesheet(custom_css, skip_whitespace=True)
    parts: list[str] = []

    for rule in tokens:
        if rule.type == "qualified-rule":
            # Reconstruct the selector and prepend .fdash-root
            selector = tinycss2.serialize(rule.prelude).strip()
            body = tinycss2.serialize(rule.content)

            # Handle comma-separated selectors
            selectors = [s.strip() for s in selector.split(",")]
            scoped = ", ".join(f".fdash-root {s}" for s in selectors)
            parts.append(f"{scoped} {{{body}}}")
        elif rule.type == "at-rule":
            # Pass through @media, @keyframes etc
            parts.append(tinycss2.serialize([rule]))

    return "\n".join(parts)


def _scope_basic(custom_css: str) -> str:
    """Basic CSS scoping without tinycss2.

    Handles simple rulesets by prepending .fdash-root to selectors.
    Does not handle nested @-rules perfectly but covers common cases.
    """
    import re

    result: list[str] = []
    # Split on closing brace to find rule blocks
    blocks = re.split(r"(\})", custom_css)

    i = 0
    while i < len(blocks):
        block = blocks[i]
        if "{" in block:
            # This contains a selector and opening brace
            parts = block.split("{", 1)
            selector = parts[0].strip()
            body = parts[1] if len(parts) > 1 else ""

            if selector.startswith("@"):
                # @-rule -- pass through
                result.append(block)
            else:
                # Scope each comma-separated selector
                selectors = [s.strip() for s in selector.split(",")]
                scoped = ", ".join(f".fdash-root {s}" for s in selectors if s)
                result.append(f"{scoped} {{{body}")
        else:
            result.append(block)
        i += 1

    return "".join(result)

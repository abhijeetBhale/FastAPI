"""Reusable helpers with no knowledge of this application's domain.

A function belongs here only if it would be equally at home in an unrelated
project — string and path manipulation, small pure transforms. Anything that
knows what a "submission" or a "cargo type" is belongs in `services/`, and
anything that speaks HTTP belongs in `api/`.

Deliberately empty for now: creating the package ahead of its first inhabitant
keeps the layout stable, and a helper that satisfies the rule above has an
obvious home the moment it appears.
"""

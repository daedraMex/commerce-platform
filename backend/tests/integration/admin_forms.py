def inline(prefix, rows=(), initial=0):
    """The formset an admin page posts for an inline: its management form plus ``rows``.

    ``initial`` counts the leading rows that edit existing objects rather than add new ones.
    """
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": str(initial),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for index, row in enumerate(rows):
        data.update({f"{prefix}-{index}-{field}": value for field, value in row.items()})
    return data


def empty_inline(prefix):
    """The management form an admin page posts for an inline the user left empty."""
    return inline(prefix)


# Every inline on the Store change page; a new inline is added here, not in each test.
STORE_ADMIN_EMPTY_INLINES = {**empty_inline("memberships"), **empty_inline("feature_flags")}

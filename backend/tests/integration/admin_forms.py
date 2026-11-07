from html.parser import HTMLParser


class FieldNameParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.names = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"input", "select", "textarea"} and attributes.get("name"):
            self.names.append(attributes["name"])


def rendered_field_names(response):
    """The field names the admin page actually rendered."""
    parser = FieldNameParser()
    parser.feed(response.content.decode())
    return parser.names


def rendered_form_data(response, values):
    """Keep only the submitted values whose field the page rendered."""
    names = set(rendered_field_names(response))
    return {name: value for name, value in values.items() if name in names}


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

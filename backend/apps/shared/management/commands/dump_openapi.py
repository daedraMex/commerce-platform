"""Write the OpenAPI schema the web clients are generated from.

The output is sorted and indented so two runs always produce the same bytes.
``--check`` compares the committed file with the generated schema and fails
when they differ, so drift cannot reach ``main``.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

REGENERATE = "uv run python manage.py dump_openapi"


class Command(BaseCommand):
    help = "Write the committed OpenAPI schema, or check it is up to date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            help=f"File to write instead of {self._default_output()}.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Fail when the committed file differs from the generated schema.",
        )

    def handle(self, *args, **options):
        output = Path(options["output"]) if options["output"] else self._default_output()
        rendered = self._render(self._generate())

        if options["check"]:
            self._check(output, rendered)
            return

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        self.stdout.write(f"Wrote {output}.")

    def _default_output(self):
        return Path(settings.BASE_DIR).parent / "packages" / "api-client" / "openapi.json"

    def _generate(self):
        # Imported lazily so importing apps.shared never needs Django's app registry.
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        if schema is None:
            raise CommandError("The OpenAPI schema could not be generated.")
        return schema

    def _render(self, schema):
        return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def _check(self, output, rendered):
        try:
            committed = output.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise CommandError(
                f"{output} does not exist. Regenerate it with:\n  {REGENERATE}"
            ) from error

        if committed != rendered:
            raise CommandError(f"{output} is out of date. Regenerate it with:\n  {REGENERATE}")

        self.stdout.write(f"{output} is up to date.")

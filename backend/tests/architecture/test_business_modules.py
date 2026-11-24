"""Modules with business rules keep DRF thin: no ModelViewSet or ModelSerializer.

The AST check reads a class's direct bases, so two ways around it are checked on
the imported classes instead, through their whole MRO (#178): inheriting through
a base class from another module, and composing DRF's writing mixins
(``CreateModelMixin``, ``UpdateModelMixin``, ``DestroyModelMixin``, which save
through the serializer) by hand. Reading mixins (list, retrieve) stay allowed.
"""

import ast
import importlib
import inspect

from rest_framework import mixins, serializers, viewsets

from tests.architecture.support import (
    APPS_DIR,
    BACKEND_DIR,
    business_modules,
    parse,
    relative,
    source_files,
)

BANNED_ANCESTORS = (
    viewsets.ModelViewSet,
    serializers.ModelSerializer,
    serializers.HyperlinkedModelSerializer,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
)

BANNED_BASES = {"ModelViewSet", "ModelSerializer", "HyperlinkedModelSerializer"}


def _base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_business_modules_are_detected():
    assert "photos" in business_modules()


def test_business_modules_define_no_model_viewset_or_serializer():
    found = [
        f"{relative(path)}:{node.name}"
        for module in business_modules()
        for path in source_files(APPS_DIR / module)
        for node in ast.walk(parse(path))
        if isinstance(node, ast.ClassDef)
        and any(_base_name(base) in BANNED_BASES for base in node.bases)
    ]

    assert found == [], "Serializers validate shape and use cases enforce rules (AGENTS.md)."


def banned_ancestors(cls):
    return [banned.__name__ for banned in BANNED_ANCESTORS if issubclass(cls, banned)]


def _dotted(path):
    return ".".join(path.relative_to(BACKEND_DIR).with_suffix("").parts).removesuffix(".__init__")


def classes_defined_in(module_name):
    module = importlib.import_module(module_name)
    return [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj) and obj.__module__ == module_name
    ]


def test_the_mro_check_sees_inherited_bases_and_composed_mixins():
    from rest_framework import generics

    class CatalogBase(serializers.ModelSerializer):
        pass

    class Derived(CatalogBase):
        pass

    class HandMade(mixins.CreateModelMixin, mixins.ListModelMixin, generics.GenericAPIView):
        pass

    class Reading(mixins.ListModelMixin, generics.GenericAPIView):
        pass

    assert banned_ancestors(Derived) == ["ModelSerializer"]
    assert banned_ancestors(HandMade) == ["CreateModelMixin"]
    assert banned_ancestors(Reading) == []
    views = {cls.__name__ for cls in classes_defined_in("apps.photos.interfaces.views")}
    assert "StaffPhotoRemoveView" in views  # the real scan imports and sees real classes


def test_business_module_classes_have_no_model_viewset_serializer_or_writing_mixin():
    found = [
        f"{cls.__module__}.{cls.__qualname__}: {', '.join(banned)}"
        for module in business_modules()
        for path in source_files(APPS_DIR / module)
        for cls in classes_defined_in(_dotted(path))
        if (banned := banned_ancestors(cls))
    ]

    assert found == [], "Serializers validate shape and use cases enforce rules (AGENTS.md)."

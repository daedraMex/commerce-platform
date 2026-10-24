# Python 3.12, Django 5.2 LTS and DRF as a thin layer

The backend uses Python 3.12 and Django 5.2 LTS, chosen for the long support window. Django REST Framework is only the transport layer: serializers validate shape and use cases enforce business rules, so `ModelViewSet` and `ModelSerializer.save()` are not used in modules with business rules.

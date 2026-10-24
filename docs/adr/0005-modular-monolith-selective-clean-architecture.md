# Modular monolith, clean architecture only where there are business rules

The backend is one deployable made of modules (one Django app per module) that talk to each other only through services or ports, never by writing another module's models. Clean architecture (domain, application, infrastructure, interfaces) is applied only to modules with business rules: inventory, orders, payments and agents. CRUD-only modules (accounts, stores, catalog) use plain Django, because the layering costs more than it returns where there are no rules to protect.

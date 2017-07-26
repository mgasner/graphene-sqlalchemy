from collections import OrderedDict

from sqlalchemy.inspection import inspect as sqlalchemyinspect
from sqlalchemy.orm.exc import NoResultFound

from graphene import Field  # , annotate, ResolveInfo
from graphene.relay import Connection, Node
from graphene.types.objecttype import ObjectType, ObjectTypeOptions
from graphene.types.utils import yank_fields_from_attrs

from .converter import (convert_sqlalchemy_column,
                        convert_sqlalchemy_composite,
                        convert_sqlalchemy_relationship)
from .registry import Registry, get_global_registry
from .utils import get_query, is_mapped


def construct_fields(model, registry, only_fields, exclude_fields):
    inspected_model = sqlalchemyinspect(model)

    fields = OrderedDict()

    for name, column in inspected_model.columns.items():
        is_not_in_only = only_fields and name not in only_fields
        # is_already_created = name in options.fields
        is_excluded = name in exclude_fields  # or is_already_created
        if is_not_in_only or is_excluded:
            # We skip this field if we specify only_fields and is not
            # in there. Or when we excldue this field in exclude_fields
            continue
        converted_column = convert_sqlalchemy_column(column, registry)
        fields[name] = converted_column

    for name, composite in inspected_model.composites.items():
        is_not_in_only = only_fields and name not in only_fields
        # is_already_created = name in options.fields
        is_excluded = name in exclude_fields  # or is_already_created
        if is_not_in_only or is_excluded:
            # We skip this field if we specify only_fields and is not
            # in there. Or when we excldue this field in exclude_fields
            continue
        converted_composite = convert_sqlalchemy_composite(composite, registry)
        fields[name] = converted_composite

    # Get all the columns for the relationships on the model
    for relationship in inspected_model.relationships:
        is_not_in_only = only_fields and relationship.key not in only_fields
        # is_already_created = relationship.key in options.fields
        is_excluded = relationship.key in exclude_fields  # or is_already_created
        if is_not_in_only or is_excluded:
            # We skip this field if we specify only_fields and is not
            # in there. Or when we excldue this field in exclude_fields
            continue
        converted_relationship = convert_sqlalchemy_relationship(relationship, registry)
        name = relationship.key
        fields[name] = converted_relationship

    return fields


class SQLAlchemyObjectTypeOptions(ObjectTypeOptions):
    model = None  # type: Model
    registry = None  # type: Registry
    connection = None  # type: Type[Connection]
    id = None  # type: str


class SQLAlchemyObjectType(ObjectType):
    @classmethod
    def __init_subclass_with_meta__(cls, model=None, registry=None, skip_registry=False,
                                    only_fields=(), exclude_fields=(), connection=None,
                                    use_connection=None, interfaces=(), id=None, **options):
        assert is_mapped(model), (
            'You need to pass a valid SQLAlchemy Model in '
            '{}.Meta, received "{}".'
        ).format(cls.__name__, model)

        if not registry:
            registry = get_global_registry()

        assert isinstance(registry, Registry), (
            'The attribute registry in {} needs to be an instance of '
            'Registry, received "{}".'
        ).format(cls.__name__, registry)

        sqla_fields = yank_fields_from_attrs(
            construct_fields(model, registry, only_fields, exclude_fields),
            _as=Field,
        )

        if use_connection is None and interfaces:
            use_connection = any((issubclass(interface, Node) for interface in interfaces))

        if use_connection and not connection:
            # We create the connection automatically
            connection = Connection.create_type('{}Connection'.format(cls.__name__), node=cls)

        if connection is not None:
            assert issubclass(connection, Connection), (
                "The connection must be a Connection. Received {}"
            ).format(connection.__name__)

        _meta = SQLAlchemyObjectTypeOptions(cls)
        _meta.model = model
        _meta.registry = registry
        _meta.fields = sqla_fields
        _meta.connection = connection
        _meta.id = id or 'id'

        super(SQLAlchemyObjectType, cls).__init_subclass_with_meta__(_meta=_meta, interfaces=interfaces, **options)

        if not skip_registry:
            registry.register(cls)

    @classmethod
    def is_type_of(cls, root, context, info):
        if isinstance(root, cls):
            return True
        if not is_mapped(type(root)):
            raise Exception((
                'Received incompatible instance "{}".'
            ).format(root))
        return isinstance(root, cls._meta.model)

    @classmethod
    def get_query(cls, context):
        model = cls._meta.model
        return get_query(model, context)

    @classmethod
    def get_node(cls, id, context, info):
        try:
            return cls.get_query(context).get(id)
        except NoResultFound:
            return None

    # @annotate(info=ResolveInfo)
    def resolve_id(self):
        # graphene_type = info.parent_type.graphene_type
        return self.__mapper__.primary_key_from_instance(self)[0]

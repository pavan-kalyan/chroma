from typing import ClassVar, Dict, Optional, Sequence
from uuid import UUID

from overrides import override
from chromadb.api import AdminAPI, ClientAPI, ServerAPI
from chromadb.api.types import (
    CollectionMetadata,
    Documents,
    EmbeddingFunction,
    Embeddings,
    GetResult,
    IDs,
    Include,
    Metadatas,
    QueryResult,
)
from chromadb.config import Settings, System
from chromadb.telemetry import Telemetry
from chromadb.telemetry.events import ClientStartEvent
from chromadb.config import DEFAULT_TENANT, DEFAULT_DATABASE
from chromadb.api.models.Collection import Collection
from chromadb.types import Where, WhereDocument
import chromadb.utils.embedding_functions as ef


class SharedSystemClient:
    _identifer_to_system: ClassVar[Dict[str, System]] = {}
    _identifier: str

    # region Initialization
    def __init__(
        self,
        settings: Settings = Settings(),
    ) -> None:
        self._identifier = SharedSystemClient._get_identifier_from_settings(settings)
        SharedSystemClient._create_system_if_not_exists(self._identifier, settings)

    @classmethod
    def _create_system_if_not_exists(
        cls, identifier: str, settings: Settings
    ) -> System:
        if identifier not in cls._identifer_to_system:
            new_system = System(settings)
            cls._identifer_to_system[identifier] = new_system

            new_system.instance(Telemetry)
            new_system.instance(ServerAPI)

            new_system.start()
        else:
            previous_system = cls._identifer_to_system[identifier]

            # For now, the settings must match
            if previous_system.settings != settings:
                raise ValueError(
                    f"An instance of Chroma already exists for {identifier} with different settings"
                )

        return cls._identifer_to_system[identifier]

    @staticmethod
    def _get_identifier_from_settings(settings: Settings) -> str:
        identifier = ""
        api_impl = settings.chroma_api_impl

        if api_impl is None:
            raise ValueError("Chroma API implementation must be set in settings")
        elif api_impl == "chromadb.api.segment.SegmentAPI":
            if settings.is_persistent:
                identifier = settings.persist_directory
            else:
                identifier = (
                    "ephemeral"  # TODO: support pathing and  multiple ephemeral clients
                )
        elif api_impl == "chromadb.api.fastapi.FastAPI":
            identifier = (
                f"{settings.chroma_server_host}:{settings.chroma_server_http_port}"
            )
        else:
            raise ValueError(f"Unsupported Chroma API implementation {api_impl}")

        return identifier

    @staticmethod
    def clear_system_cache() -> None:
        SharedSystemClient._identifer_to_system = {}

    @property
    def _system(self) -> System:
        return SharedSystemClient._identifer_to_system[self._identifier]

    # endregion


class Client(SharedSystemClient, ClientAPI):
    """A client for Chroma. This is the main entrypoint for interacting with Chroma.
    A client internally stores its tenant and database and proxies calls to a
    Server API instance of Chroma. It treats the Server API and corresponding System
    as a singleton, so multiple clients connecting to the same resource will share the
    same API instance.

    Client implementations should be implement their own API-caching strategies.
    """

    tenant: str = DEFAULT_TENANT
    database: str = DEFAULT_DATABASE

    _server: ServerAPI

    # region Initialization
    def __init__(
        self,
        tenant: str = "default",
        database: str = "default",
        settings: Settings = Settings(),
    ) -> None:
        super().__init__(settings=settings)
        self.tenant = tenant
        self.database = database

        # Get the root system component we want to interact with
        self._server = self._system.instance(ServerAPI)

        # Submit event for a client start
        telemetry_client = self._system.instance(Telemetry)
        telemetry_client.capture(ClientStartEvent())

    # endregion

    # region BaseAPI Methods
    # Note - we could do this in less verbose ways, but they break type checking
    @override
    def heartbeat(self) -> int:
        return self._server.heartbeat()

    @override
    def list_collections(self) -> Sequence[Collection]:
        return self._server.list_collections(tenant=self.tenant, database=self.database)

    @override
    def create_collection(
        self,
        name: str,
        metadata: Optional[CollectionMetadata] = None,
        embedding_function: Optional[EmbeddingFunction] = ef.DefaultEmbeddingFunction(),
        get_or_create: bool = False,
    ) -> Collection:
        return self._server.create_collection(
            name=name,
            metadata=metadata,
            embedding_function=embedding_function,
            tenant=self.tenant,
            database=self.database,
            get_or_create=get_or_create,
        )

    @override
    def get_collection(
        self,
        name: str,
        embedding_function: Optional[EmbeddingFunction] = ef.DefaultEmbeddingFunction(),
    ) -> Collection:
        return self._server.get_collection(
            name=name,
            embedding_function=embedding_function,
            tenant=self.tenant,
            database=self.database,
        )

    @override
    def get_or_create_collection(
        self,
        name: str,
        metadata: Optional[CollectionMetadata] = None,
        embedding_function: Optional[EmbeddingFunction] = ef.DefaultEmbeddingFunction(),
    ) -> Collection:
        return self._server.get_or_create_collection(
            name=name,
            metadata=metadata,
            embedding_function=embedding_function,
            tenant=self.tenant,
            database=self.database,
        )

    @override
    def _modify(
        self,
        id: UUID,
        new_name: Optional[str] = None,
        new_metadata: Optional[CollectionMetadata] = None,
    ) -> None:
        return self._server._modify(
            id=id,
            new_name=new_name,
            new_metadata=new_metadata,
        )

    @override
    def delete_collection(
        self,
        name: str,
    ) -> None:
        return self._server.delete_collection(
            name=name,
            tenant=self.tenant,
            database=self.database,
        )

    #
    # ITEM METHODS
    #

    @override
    def _add(
        self,
        ids: IDs,
        collection_id: UUID,
        embeddings: Embeddings,
        metadatas: Optional[Metadatas] = None,
        documents: Optional[Documents] = None,
    ) -> bool:
        return self._server._add(
            ids=ids,
            collection_id=collection_id,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    @override
    def _update(
        self,
        collection_id: UUID,
        ids: IDs,
        embeddings: Optional[Embeddings] = None,
        metadatas: Optional[Metadatas] = None,
        documents: Optional[Documents] = None,
    ) -> bool:
        return self._server._update(
            collection_id=collection_id,
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    @override
    def _upsert(
        self,
        collection_id: UUID,
        ids: IDs,
        embeddings: Embeddings,
        metadatas: Optional[Metadatas] = None,
        documents: Optional[Documents] = None,
    ) -> bool:
        return self._server._upsert(
            collection_id=collection_id,
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    @override
    def _count(self, collection_id: UUID) -> int:
        return self._server._count(
            collection_id=collection_id,
        )

    @override
    def _peek(self, collection_id: UUID, n: int = 10) -> GetResult:
        return self._server._peek(
            collection_id=collection_id,
            n=n,
        )

    @override
    def _get(
        self,
        collection_id: UUID,
        ids: Optional[IDs] = None,
        where: Optional[Where] = {},
        sort: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        where_document: Optional[WhereDocument] = {},
        include: Include = ["embeddings", "metadatas", "documents"],
    ) -> GetResult:
        return self._server._get(
            collection_id=collection_id,
            ids=ids,
            where=where,
            sort=sort,
            limit=limit,
            offset=offset,
            page=page,
            page_size=page_size,
            where_document=where_document,
            include=include,
        )

    def _delete(
        self,
        collection_id: UUID,
        ids: Optional[IDs],
        where: Optional[Where] = {},
        where_document: Optional[WhereDocument] = {},
    ) -> IDs:
        return self._server._delete(
            collection_id=collection_id,
            ids=ids,
            where=where,
            where_document=where_document,
        )

    @override
    def _query(
        self,
        collection_id: UUID,
        query_embeddings: Embeddings,
        n_results: int = 10,
        where: Where = {},
        where_document: WhereDocument = {},
        include: Include = ["embeddings", "metadatas", "documents", "distances"],
    ) -> QueryResult:
        return self._server._query(
            collection_id=collection_id,
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where,
            where_document=where_document,
            include=include,
        )

    @override
    def reset(self) -> bool:
        return self._server.reset()

    @override
    def get_version(self) -> str:
        return self._server.get_version()

    @override
    def get_settings(self) -> Settings:
        return self._server.get_settings()

    @property
    @override
    def max_batch_size(self) -> int:
        return self._server.max_batch_size

    # endregion

    # region ClientAPI Methods

    @override
    def set_database(self, database: str) -> None:
        self.database = database

    @override
    def set_tenant(self, tenant: str) -> None:
        self.tenant = tenant

    # endregion


class AdminClient(AdminAPI, SharedSystemClient):
    _server: ServerAPI

    def __init__(self, settings: Settings = Settings()) -> None:
        super().__init__(settings)
        self._server = self._system.instance(ServerAPI)

    @override
    def create_database(self, name: str, tenant: str = DEFAULT_TENANT) -> None:
        return self._server.create_database(name=name, tenant=tenant)
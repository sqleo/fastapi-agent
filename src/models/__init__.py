"""导入所有带 ``table=True`` 的模型，供 ``SQLModel.metadata.create_all`` 注册表结构."""

from models.EntityDictionaryModel import (  # noqa: F401
    EntityAliasModel,
    EntityCandidateModel,
    EntityDictionaryModel,
)
from models.FileManagementModel import FileAssetModel, FileFolderModel  # noqa: F401
from models.KnowledgeBaseModel import (  # noqa: F401
    KnowledgeBaseFileModel,
    KnowledgeBaseModel,
)
from models.LlmGlobalSettingModel import LlmGlobalSettingModel  # noqa: F401
from models.LlmVendorModel import LlmVendorModel  # noqa: F401
from models.UserAgentToolSettingsModel import UserAgentToolSettingsModel  # noqa: F401
from models.UserModel import UserModel  # noqa: F401

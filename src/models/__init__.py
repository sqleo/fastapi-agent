"""导入所有带 ``table=True`` 的模型，供 ``SQLModel.metadata.create_all`` 注册表结构。"""

from models.KbExtractedImageModel import KbExtractedImageModel  # noqa: F401
from models.KbFileModel import KbFileModel  # noqa: F401
from models.KnowledgeModel import KnowledgeModel  # noqa: F401
from models.UserModel import UserModel  # noqa: F401

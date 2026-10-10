"""统一异常体系。

业务层只捕获该体系内的异常，避免把第三方库异常直接暴露给接口调用方。
"""


class KaoyanError(Exception):
    """业务异常基类。"""


class ConfigurationError(KaoyanError):
    """配置缺失或不合法。"""


class PromptError(KaoyanError):
    """提示词组装失败，例如缺少必需变量。"""


class LLMError(KaoyanError):
    """模型调用失败。"""


class StructuredOutputError(LLMError):
    """模型输出无法解析为目标结构。"""

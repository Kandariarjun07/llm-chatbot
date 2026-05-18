from dataclasses import dataclass
from string import Formatter
from typing import Any

from prompts.assistant import (
    BIGDATA_ANALYSIS_STYLE,
    RESPONSE_STYLE,
    SQL_EXPLANATION_STYLE,
    RESEARCH_STYLE,
)
from prompts.formatters import (
    BIGDATA_ANALYSIS_PROMPT,
    RAG_ANSWER_PROMPT,
    SQL_EXPLANATION_PROMPT,
    WEB_SEARCH_PROMPT,
)
from prompts.system import SYSTEM_ROLE
from prompts.tools import TOOL_SELECTION_PROMPT, TOOL_SELECTOR_ROLE


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    system: str
    user: str


class PromptManager:
    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        self.register(
            "basic",
            system=SYSTEM_ROLE,
            user="{query}",
        )
        self.register(
            "rag_answer",
            system=SYSTEM_ROLE + "\n" + RESPONSE_STYLE,
            user=RAG_ANSWER_PROMPT,
        )
        self.register(
            "tool_selector",
            system=TOOL_SELECTOR_ROLE,
            user=TOOL_SELECTION_PROMPT,
        )
        self.register(
            "bigdata_analysis",
            system=SYSTEM_ROLE + "\n" + BIGDATA_ANALYSIS_STYLE,
            user=BIGDATA_ANALYSIS_PROMPT,
        )
        self.register(
            "sql_explanation",
            system=SYSTEM_ROLE + "\n" + SQL_EXPLANATION_STYLE,
            user=SQL_EXPLANATION_PROMPT,
        )
        self.register(
            "research",
            system=SYSTEM_ROLE + "\n" + RESEARCH_STYLE,
            user=RAG_ANSWER_PROMPT,
        )
        self.register(
            "web_search",
            system=SYSTEM_ROLE + "\nYou have access to real-time web search results. Use ONLY those results. Do not rely on training data.",
            user=WEB_SEARCH_PROMPT,
        )

    def register(self, name: str, *, system: str, user: str) -> None:
        self._templates[name] = PromptTemplate(name=name, system=system, user=user)

    def get(self, name: str) -> PromptTemplate:
        if name not in self._templates:
            available = ", ".join(sorted(self._templates))
            raise KeyError(f"Unknown prompt template '{name}'. Available: {available}")
        return self._templates[name]

    def render(self, template_text: str, **kwargs: Any) -> str:
        cleaned_kwargs = {
            key: self._normalize_value(value)
            for key, value in kwargs.items()
        }
        return template_text.format_map(SafeFormatDict(cleaned_kwargs))

    def compose(self, name: str, **kwargs: Any) -> list[dict[str, str]]:
        template = self.get(name)
        return [
            {
                "role": "system",
                "content": self.render(template.system, **kwargs),
            },
            {
                "role": "user",
                "content": self.render(template.user, **kwargs),
            },
        ]

    def required_variables(self, name: str) -> list[str]:
        template = self.get(name)
        variables = set()
        formatter = Formatter()

        for text in (template.system, template.user):
            for _, field_name, _, _ in formatter.parse(text):
                if field_name:
                    variables.add(field_name.split(".", 1)[0])

        return sorted(variables)

    def available_templates(self) -> list[str]:
        return sorted(self._templates)

    def _normalize_value(self, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, list):
            return "\n\n".join(str(item) for item in value)

        return str(value)


prompt_manager = PromptManager()

"""
Custom fields module.

Handles creation of custom fields, contexts, and options.
"""

import asyncio
import random
from datetime import datetime
from typing import Optional

from .base import JiraAPIClient

# Custom field type definitions with their searcher keys
# Reference: https://support.atlassian.com/jira/kb/jira-software-rest-api-essential-parameters-for-custom-field-creation/
CUSTOM_FIELD_TYPES = {
    "textfield": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
        "description": "Text Field (single line)",
    },
    "textarea": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
        "description": "Text Field (multi-line)",
    },
    "float": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:float",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:exactnumber",
        "description": "Number Field",
    },
    "datepicker": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:daterange",
        "description": "Date Picker",
    },
    "datetime": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:datetime",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:datetimerange",
        "description": "Date Time Picker",
    },
    "select": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:select",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
        "description": "Select List (single choice)",
        "has_options": True,
    },
    "multiselect": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:multiselect",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
        "description": "Select List (multiple choices)",
        "has_options": True,
    },
    "radiobuttons": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:radiobuttons",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
        "description": "Radio Buttons",
        "has_options": True,
    },
    "multicheckboxes": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:multicheckboxes",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
        "description": "Checkboxes",
        "has_options": True,
    },
    "userpicker": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:userpicker",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:userpickergroupsearcher",
        "description": "User Picker (single user)",
    },
    "multiuserpicker": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:multiuserpicker",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:userpickergroupsearcher",
        "description": "User Picker (multiple users)",
    },
    "grouppicker": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:grouppicker",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:grouppickersearcher",
        "description": "Group Picker (single group)",
    },
    "multigrouppicker": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:multigrouppicker",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:grouppickersearcher",
        "description": "Group Picker (multiple groups)",
    },
    "cascadingselect": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:cascadingselect",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:cascadingselectsearcher",
        "description": "Select List (cascading)",
        "has_options": True,
    },
    "labels": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:labels",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:labelsearcher",
        "description": "Labels",
    },
    "url": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:url",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:exacttextsearcher",
        "description": "URL Field",
    },
    "project": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:project",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:projectsearcher",
        "description": "Project Picker (single project)",
    },
    "version": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:version",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:versionsearcher",
        "description": "Version Picker (single version)",
    },
    "multiversion": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:multiversion",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:versionsearcher",
        "description": "Version Picker (multiple versions)",
    },
    "readonlyfield": {
        "type": "com.atlassian.jira.plugin.system.customfieldtypes:readonlyfield",
        "searcherKey": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
        "description": "Text Field (read only)",
    },
}

# Field types to use when generating random custom fields (excluding read-only)
GENERATABLE_FIELD_TYPES = [
    "textfield",
    "textarea",
    "float",
    "datepicker",
    "datetime",
    "select",
    "multiselect",
    "radiobuttons",
    "multicheckboxes",
    "userpicker",
    "labels",
    "url",
]


class CustomFieldGenerator(JiraAPIClient):
    """Generates custom fields, contexts, and options for Jira."""

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        prefix: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark=None,
        request_delay: float = 0.0,
    ):
        super().__init__(jira_url, email, api_token, dry_run, concurrency, benchmark, request_delay)
        self.prefix = prefix
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Track created items
        self.created_fields: list[dict] = []
        self.created_contexts: list[dict] = []
        self.created_options: list[dict] = []

    def set_run_id(self, run_id: str):
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== CUSTOM FIELDS ==========

    def create_custom_field(self, name: str, field_type: str, description: Optional[str] = None) -> Optional[dict]:
        """Create a custom field.

        Args:
            name: Field name
            field_type: Field type key (e.g., 'textfield', 'select')
            description: Field description

        Returns:
            Field dict with 'id', 'name', 'type' or None on failure
        """
        if field_type not in CUSTOM_FIELD_TYPES:
            self.logger.error(f"Unknown field type: {field_type}")
            return None

        field_config = CUSTOM_FIELD_TYPES[field_type]

        field_data = {"name": name, "type": field_config["type"], "searcherKey": field_config["searcherKey"]}

        if description:
            field_data["description"] = description

        if self.dry_run:
            field_id = f"customfield_{random.randint(10000, 99999)}"
            field_obj = {"id": field_id, "name": name, "type": field_type, "schema": {"type": field_type}}
            self.created_fields.append(field_obj)
            return field_obj

        response = self._api_call("POST", "field", data=field_data)
        if response:
            field_obj = response.json()
            field_obj["type_key"] = field_type  # Store our type key for reference
            self.created_fields.append(field_obj)
            return field_obj
        return None

    def create_custom_fields(self, count: int) -> list[dict]:
        """Create multiple custom fields with varying types.

        Args:
            count: Number of custom fields to create

        Returns:
            List of created field dicts
        """
        self.logger.info(f"Creating {count} custom fields...")

        fields = []

        for i in range(count):
            # Cycle through different field types
            field_type = GENERATABLE_FIELD_TYPES[i % len(GENERATABLE_FIELD_TYPES)]
            type_desc = CUSTOM_FIELD_TYPES[field_type]["description"]

            name = f"{self.prefix} {type_desc} {i + 1}"
            description = f"Test custom field ({type_desc}) - {self.run_id}"

            field_obj = self.create_custom_field(name=name, field_type=field_type, description=description)

            if field_obj:
                fields.append(field_obj)
                self.logger.info(f"Created custom field {i + 1}/{count}: {name} ({field_type})")

                # If this field type supports options, create some
                if CUSTOM_FIELD_TYPES[field_type].get("has_options"):
                    self._create_field_options_for_field(field_obj, num_options=5)

        return fields

    # ========== FIELD CONTEXTS ==========

    def get_field_contexts(self, field_id: str) -> list[dict]:
        """Get contexts for a custom field.

        Args:
            field_id: The field ID (e.g., 'customfield_10001')

        Returns:
            List of context dicts
        """
        if self.dry_run:
            return [{"id": str(random.randint(10000, 99999)), "name": "Default Context"}]

        response = self._api_call("GET", f"field/{field_id}/context")
        if response:
            return response.json().get("values", [])
        return []

    def create_field_context(
        self,
        field_id: str,
        name: str,
        description: Optional[str] = None,
        project_ids: Optional[list[str]] = None,
        issue_type_ids: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Create a context for a custom field.

        Args:
            field_id: The field ID (e.g., 'customfield_10001')
            name: Context name
            description: Context description
            project_ids: List of project IDs (empty for global)
            issue_type_ids: List of issue type IDs (empty for all)

        Returns:
            Context dict or None on failure
        """
        context_data = {"name": name}

        if description:
            context_data["description"] = description
        if project_ids:
            context_data["projectIds"] = project_ids
        if issue_type_ids:
            context_data["issueTypeIds"] = issue_type_ids

        if self.dry_run:
            context = {"id": str(random.randint(10000, 99999)), "name": name, "fieldId": field_id}
            self.created_contexts.append(context)
            return context

        response = self._api_call("POST", f"field/{field_id}/context", data=context_data)
        if response:
            result = response.json()
            # The API returns a wrapper with 'values' array
            contexts = result.get("values", [result])
            if contexts:
                context = contexts[0]
                self.created_contexts.append(context)
                return context
        return None

    # ========== FIELD OPTIONS ==========

    def create_field_options(self, field_id: str, context_id: str, options: list[str]) -> list[dict]:
        """Create options for a select-type custom field.

        Args:
            field_id: The field ID (e.g., 'customfield_10001')
            context_id: The context ID
            options: List of option values to create

        Returns:
            List of created option dicts
        """
        if not options:
            return []

        options_data = {"options": [{"value": opt, "disabled": False} for opt in options]}

        if self.dry_run:
            created = []
            for _i, opt in enumerate(options):
                option = {"id": str(random.randint(10000, 99999)), "value": opt, "disabled": False}
                created.append(option)
                self.created_options.append(option)
            return created

        response = self._api_call("POST", f"field/{field_id}/context/{context_id}/option", data=options_data)

        if response:
            result = response.json()
            created_options = result.get("options", [])
            self.created_options.extend(created_options)
            return created_options
        return []

    def _create_field_options_for_field(self, field_obj: dict, num_options: int = 5) -> list[dict]:
        """Helper to create options for a newly created field.

        Gets the default context and creates options.
        """
        field_id = field_obj.get("id")
        if not field_id:
            return []

        # Get contexts for this field
        contexts = self.get_field_contexts(field_id)
        if not contexts:
            self.logger.warning(f"No contexts found for field {field_id}")
            return []

        # Use the first (default) context
        context_id = contexts[0].get("id")
        if not context_id:
            return []

        # Generate option values
        option_values = [f"{self.prefix} Option {i + 1}" for i in range(num_options)]

        options = self.create_field_options(field_id, context_id, option_values)
        if options:
            self.logger.debug(f"Created {len(options)} options for field {field_id}")
        return options

    # ========== ASYNC METHODS ==========

    async def create_custom_fields_async(self, count: int) -> list[dict]:
        """Create multiple custom fields concurrently.

        Note: Field creation must be somewhat sequential because
        we need to create options for select-type fields after
        the field is created. However, we can parallelize the
        non-dependent parts.

        Args:
            count: Number of custom fields to create

        Returns:
            List of created field dicts
        """
        self.logger.info(f"Creating {count} custom fields (concurrency: {self.concurrency})...")

        # Pre-generate all field data
        field_requests = []
        for i in range(count):
            field_type = GENERATABLE_FIELD_TYPES[i % len(GENERATABLE_FIELD_TYPES)]
            type_desc = CUSTOM_FIELD_TYPES[field_type]["description"]
            field_config = CUSTOM_FIELD_TYPES[field_type]

            field_data = {
                "name": f"{self.prefix} {type_desc} {i + 1}",
                "type": field_config["type"],
                "searcherKey": field_config["searcherKey"],
                "description": f"Test custom field ({type_desc}) - {self.run_id}",
            }
            field_requests.append((field_data, field_type))

        # Create fields in batches
        fields = []
        batch_size = self.concurrency * 2

        for i in range(0, len(field_requests), batch_size):
            batch = field_requests[i : i + batch_size]
            tasks = [self._api_call_async("POST", "field", data=fd) for fd, _ in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for idx, result in enumerate(results):
                field_type = batch[idx][1]
                if isinstance(result, tuple) and result[0] and result[1]:
                    field_obj = result[1]
                    field_obj["type_key"] = field_type
                    fields.append(field_obj)
                    self.created_fields.append(field_obj)
                elif self.dry_run:
                    field_id = f"customfield_{random.randint(10000, 99999)}"
                    field_obj = {
                        "id": field_id,
                        "name": batch[idx][0]["name"],
                        "type_key": field_type,
                        "schema": {"type": field_type},
                    }
                    fields.append(field_obj)
                    self.created_fields.append(field_obj)

            self.logger.info(f"Created {len(fields)}/{count} custom fields")

        # Create options for select-type fields (must be sequential after field creation)
        await self._create_options_for_fields_async(fields)

        return fields

    async def _create_options_for_fields_async(self, fields: list[dict]) -> None:
        """Create options for all select-type fields.

        Args:
            fields: List of field dicts that were created
        """
        select_fields = [
            f for f in fields if f.get("type_key") and CUSTOM_FIELD_TYPES.get(f["type_key"], {}).get("has_options")
        ]

        if not select_fields:
            return

        self.logger.info(f"Creating options for {len(select_fields)} select-type fields...")

        # Get contexts for all select fields in parallel
        context_tasks = []
        for field_obj in select_fields:
            field_id = field_obj.get("id")
            if field_id:
                context_tasks.append(self._get_field_contexts_async(field_id))

        context_results = await asyncio.gather(*context_tasks, return_exceptions=True)

        # Create options for each field
        option_tasks = []
        for i, field_obj in enumerate(select_fields):
            field_id = field_obj.get("id")
            if not field_id:
                continue

            contexts = context_results[i] if isinstance(context_results[i], list) else []
            if not contexts:
                continue

            context_id = contexts[0].get("id")
            if not context_id:
                continue

            option_values = [f"{self.prefix} Option {j + 1}" for j in range(5)]
            options_data = {"options": [{"value": opt, "disabled": False} for opt in option_values]}
            option_tasks.append(
                self._api_call_async("POST", f"field/{field_id}/context/{context_id}/option", data=options_data)
            )

        if option_tasks:
            results = await asyncio.gather(*option_tasks, return_exceptions=True)
            created_count = sum(1 for r in results if (isinstance(r, tuple) and r[0]) or self.dry_run)
            self.logger.info(f"Created options for {created_count} fields")

    async def _get_field_contexts_async(self, field_id: str) -> list[dict]:
        """Get contexts for a custom field asynchronously."""
        if self.dry_run:
            return [{"id": str(random.randint(10000, 99999)), "name": "Default Context"}]

        success, result = await self._api_call_async("GET", f"field/{field_id}/context")
        if success and result:
            return result.get("values", [])
        return []

    # ========== FIELD CONFIGURATION ==========

    def get_field_configurations(self) -> list[dict]:
        """Get all field configurations.

        Returns:
            List of field configuration dicts
        """
        if self.dry_run:
            return [{"id": 10000, "name": "Default Field Configuration"}]

        response = self._api_call("GET", "fieldconfiguration")
        if response:
            return response.json().get("values", [])
        return []

    def create_field_configuration(self, name: str, description: Optional[str] = None) -> Optional[dict]:
        """Create a field configuration.

        Args:
            name: Configuration name
            description: Configuration description

        Returns:
            Field configuration dict or None on failure
        """
        config_data = {"name": name}
        if description:
            config_data["description"] = description

        if self.dry_run:
            return {"id": random.randint(10000, 99999), "name": name, "description": description or ""}

        response = self._api_call("POST", "fieldconfiguration", data=config_data)
        if response:
            return response.json()
        return None

    def create_field_configuration_scheme(self, name: str, description: Optional[str] = None) -> Optional[dict]:
        """Create a field configuration scheme.

        Args:
            name: Scheme name
            description: Scheme description

        Returns:
            Field configuration scheme dict or None on failure
        """
        scheme_data = {"name": name}
        if description:
            scheme_data["description"] = description

        if self.dry_run:
            return {"id": random.randint(10000, 99999), "name": name, "description": description or ""}

        response = self._api_call("POST", "fieldconfigurationscheme", data=scheme_data)
        if response:
            return response.json()
        return None

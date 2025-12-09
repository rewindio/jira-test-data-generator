"""
Project generation module.

Handles creation of projects, versions, components, categories, and properties.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import Dict, List, Optional

from .base import JiraAPIClient


class ProjectGenerator(JiraAPIClient):
    """Generates projects, versions, components, categories, and properties for Jira."""

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        prefix: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark=None
    ):
        super().__init__(jira_url, email, api_token, dry_run, concurrency, benchmark)
        self.prefix = prefix
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Track created items
        self.created_projects: List[Dict[str, str]] = []
        self.created_versions: List[str] = []
        self.created_components: List[str] = []
        self.created_categories: List[Dict[str, str]] = []

        # Current project context
        self.project_key: Optional[str] = None

    def set_run_id(self, run_id: str):
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    def get_project(self, project_key: str) -> Optional[Dict[str, str]]:
        """Fetch a project's info by key"""
        response = self._api_call('GET', f'project/{project_key}')
        if response:
            result = response.json()
            return {
                "key": result.get('key'),
                "id": result.get('id')
            }
        return None

    def get_project_admin_role_id(self, project_key: str) -> Optional[str]:
        """Get the Administrator role ID for a project"""
        if self.dry_run:
            return "10002"

        response = self._api_call('GET', f'project/{project_key}/role')
        if response:
            roles = response.json()
            for role_name, role_url in roles.items():
                if 'administrator' in role_name.lower():
                    role_id = role_url.rstrip('/').split('/')[-1]
                    return role_id
        return None

    def get_project_viewer_role_id(self, project_key: str) -> Optional[str]:
        """Get a role ID that grants view permission."""
        if self.dry_run:
            return "10002"

        response = self._api_call('GET', f'project/{project_key}/role')
        if response:
            roles = response.json()
            system_roles = ['atlassian-addons', 'system', 'service']

            def is_system_role(name):
                return any(sr in name.lower() for sr in system_roles)

            for role_name in ['Users', 'Viewers', 'Developers', 'Member', 'Team']:
                for name, role_url in roles.items():
                    if role_name.lower() in name.lower() and not is_system_role(name):
                        role_id = role_url.rstrip('/').split('/')[-1]
                        self.logger.debug(f"Found viewer role: {name} (ID: {role_id})")
                        return role_id

            for name, role_url in roles.items():
                if 'admin' in name.lower() and not is_system_role(name):
                    role_id = role_url.rstrip('/').split('/')[-1]
                    self.logger.debug(f"Using Administrators role for viewers: {name} (ID: {role_id})")
                    return role_id

            self.logger.warning(f"No suitable role found in project {project_key}. Available roles: {list(roles.keys())}")
        return None

    def add_user_to_project_role(self, project_key: str, role_id: str, account_id: str) -> bool:
        """Add a user to a project role"""
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would add user to role in {project_key}")
            return True

        data = {"user": [account_id]}
        response = self._api_call('POST', f'project/{project_key}/role/{role_id}', data=data)
        if response:
            self.logger.debug(f"Added user to role in {project_key}")
            return True
        else:
            self.logger.debug(f"Failed to add user to role in {project_key} (may already exist)")
            return False

    def add_users_to_project(self, project_key: str, user_account_ids: List[str]) -> int:
        """Add multiple users to a project so they can view issues"""
        if not user_account_ids:
            return 0

        role_id = self.get_project_viewer_role_id(project_key)
        if not role_id:
            self.logger.warning(f"Could not find viewer role for project {project_key}")
            return 0

        self.logger.info(f"Adding {len(user_account_ids)} users to project {project_key}...")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would add {len(user_account_ids)} users to project")
            return len(user_account_ids)

        added = 0
        for account_id in user_account_ids:
            if self.add_user_to_project_role(project_key, role_id, account_id):
                added += 1

        self.logger.info(f"Added {added}/{len(user_account_ids)} users to project {project_key}")
        return added

    def create_projects(self, count: int) -> List[Dict[str, str]]:
        """Create projects and return list of project info dicts with 'key' and 'id'."""
        self.logger.info(f"Creating {count} projects...")

        created_projects = []
        current_user_id = self.get_current_user_account_id()

        for i in range(count):
            project_key = f"{self.prefix[:6].upper()}{i + 1}"

            if self.dry_run:
                self.logger.info(f"DRY RUN: Would create project {project_key}")
                created_projects.append({
                    "key": project_key,
                    "id": f"1000{i}"
                })
                self.get_project_admin_role_id(project_key)
                self.add_user_to_project_role(project_key, "10002", current_user_id)
                time.sleep(0.3)
                continue

            project_data = {
                "key": project_key,
                "name": f"{self.prefix} Test Project {i + 1}",
                "description": f"Test project created by data generator. {self.generate_random_text(5, 15)}",
                "projectTypeKey": "software",
                "leadAccountId": current_user_id
            }

            response = self._api_call('POST', 'project', data=project_data)
            if response:
                result = response.json()
                created_projects.append({
                    "key": result.get('key'),
                    "id": result.get('id')
                })
                self.logger.info(f"Created project {i + 1}/{count}: {result.get('key')}")

                admin_role_id = self.get_project_admin_role_id(result.get('key'))
                if admin_role_id and current_user_id:
                    self.add_user_to_project_role(result.get('key'), admin_role_id, current_user_id)
            else:
                existing_project = self.get_project(project_key)
                if existing_project:
                    self.logger.info(f"Project {project_key} already exists, reusing it")
                    created_projects.append(existing_project)
                else:
                    self.logger.warning(f"Failed to create project {project_key}")

            time.sleep(0.3)

        self.created_projects = created_projects
        return created_projects

    def create_versions(self, project_key: str, count: int) -> List[str]:
        """Create project versions"""
        self.logger.info(f"Creating {count} versions for project {project_key}...")

        version_ids = []
        for i in range(count):
            version_data = {
                "name": f"{self.prefix} v{i + 1}.0",
                "description": f"Test version {i + 1} - {self.generate_random_text(5, 10)}",
                "project": project_key,
                "released": i < count // 2  # Half released, half unreleased
            }

            response = self._api_call('POST', 'version', data=version_data)
            if response:
                version_id = response.json().get('id')
                version_ids.append(version_id)
                self.logger.info(f"Created version {i + 1}/{count}")
            elif self.dry_run:
                version_ids.append(f"version-{i}")

            time.sleep(0.2)

        self.created_versions.extend(version_ids)
        return version_ids

    def create_components(self, project_key: str, count: int) -> List[str]:
        """Create project components"""
        self.logger.info(f"Creating {count} components for project {project_key}...")

        component_ids = []
        for i in range(count):
            component_data = {
                "name": f"{self.prefix}-Component-{i + 1}",
                "description": f"Test component - {self.generate_random_text(5, 10)}",
                "project": project_key
            }

            response = self._api_call('POST', 'component', data=component_data)
            if response:
                component_id = response.json().get('id')
                component_ids.append(component_id)
                self.logger.info(f"Created component {i + 1}/{count}")
            elif self.dry_run:
                component_ids.append(f"component-{i}")

            time.sleep(0.2)

        self.created_components.extend(component_ids)
        return component_ids

    # ========== PROJECT CATEGORIES ==========

    def create_category(self, name: str, description: Optional[str] = None) -> Optional[Dict[str, str]]:
        """Create a project category.

        Args:
            name: Category name
            description: Category description

        Returns:
            Category dict with 'id', 'name' or None on failure
        """
        category_data = {
            "name": name
        }
        if description:
            category_data["description"] = description

        if self.dry_run:
            category = {
                "id": str(random.randint(10000, 99999)),
                "name": name
            }
            self.created_categories.append(category)
            return category

        response = self._api_call('POST', 'projectCategory', data=category_data)
        if response:
            category = response.json()
            self.created_categories.append(category)
            return category
        return None

    def create_categories(self, count: int) -> List[Dict[str, str]]:
        """Create project categories.

        Args:
            count: Number of categories to create

        Returns:
            List of created category dicts
        """
        self.logger.info(f"Creating {count} project categories...")

        categories = []
        category_types = [
            "Development",
            "Operations",
            "Marketing",
            "Support",
            "Research",
            "Infrastructure",
            "Quality Assurance",
            "Documentation"
        ]

        for i in range(count):
            category_type = category_types[i % len(category_types)]
            name = f"{self.prefix} {category_type} {i + 1}"
            description = f"Test category for {category_type.lower()} projects - {self.generate_random_text(5, 10)}"

            category = self.create_category(name, description)
            if category:
                categories.append(category)
                self.logger.info(f"Created category {i + 1}/{count}: {name}")

            time.sleep(0.2)

        return categories

    def assign_project_to_category(self, project_key: str, category_id: str) -> bool:
        """Assign a project to a category.

        Args:
            project_key: Project key
            category_id: Category ID

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would assign {project_key} to category {category_id}")
            return True

        # Update project with category
        update_data = {
            "categoryId": int(category_id)
        }

        response = self._api_call('PUT', f'project/{project_key}', data=update_data)
        if response:
            self.logger.debug(f"Assigned {project_key} to category {category_id}")
            return True
        return False

    # ========== PROJECT PROPERTIES ==========

    def create_project_property(self, project_key: str, property_key: str, property_value: Dict) -> bool:
        """Create or update a project property.

        Project properties are key-value pairs that can store arbitrary JSON data.

        Args:
            project_key: Project key
            property_key: Property key name
            property_value: Property value (JSON-serializable dict)

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property {property_key} on {project_key}")
            return True

        # Note: Properties use PUT, not POST
        response = self._api_call('PUT', f'project/{project_key}/properties/{property_key}', data=property_value)
        # PUT for properties returns 200 (update) or 201 (create), both are success
        # Our _api_call returns None on dry_run but the response object otherwise
        if response is not None:
            return True
        return False

    def create_project_properties(self, project_keys: List[str], count: int) -> int:
        """Create project properties distributed across projects.

        Args:
            project_keys: List of project keys
            count: Total number of properties to create

        Returns:
            Number of properties created
        """
        self.logger.info(f"Creating {count} project properties...")

        created = 0
        failed = 0

        for i in range(count):
            project_key = project_keys[i % len(project_keys)]
            property_key = f"{self.prefix.lower()}_property_{i + 1}"

            # Generate random property data
            property_value = {
                "generatedBy": "jira-test-data-generator",
                "runId": self.run_id,
                "timestamp": datetime.now().isoformat(),
                "index": i + 1,
                "category": random.choice(["config", "metadata", "settings", "cache"]),
                "values": {
                    "enabled": random.choice([True, False]),
                    "threshold": random.randint(1, 100),
                    "mode": random.choice(["auto", "manual", "scheduled"]),
                    "description": self.generate_random_text(5, 15)
                }
            }

            if self.create_project_property(project_key, property_key, property_value):
                created += 1
            else:
                failed += 1

            if (created + failed) % 10 == 0:
                self.logger.info(f"Created {created}/{count} project properties ({failed} failed)")
                time.sleep(0.2)

        self.logger.info(f"Project properties complete: {created} created, {failed} failed")
        return created

    # ========== ASYNC METHODS ==========

    async def create_versions_async(self, project_key: str, count: int) -> List[str]:
        """Create project versions concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} versions for project {project_key} (concurrency: {self.concurrency})...")

        version_ids = []
        batch_size = self.concurrency * 2
        version_index = 0

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                version_index += 1
                version_data = {
                    "name": f"{self.prefix} v{version_index}.0",
                    "description": f"Test version {version_index} - {self.generate_random_text(5, 10)}",
                    "project": project_key,
                    "released": version_index <= count // 2  # Half released, half unreleased
                }
                tasks.append(self._api_call_async('POST', 'version', data=version_data))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0] and result[1]:
                    version_ids.append(result[1].get('id'))
                elif self.dry_run:
                    version_ids.append(f"version-{len(version_ids)}")

            self.logger.info(f"Created {len(version_ids)}/{count} versions")

        self.created_versions.extend(version_ids)
        return version_ids

    async def create_components_async(self, project_key: str, count: int) -> List[str]:
        """Create project components concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} components for project {project_key} (concurrency: {self.concurrency})...")

        component_ids = []
        batch_size = self.concurrency * 2
        component_index = 0

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                component_index += 1
                component_data = {
                    "name": f"{self.prefix}-Component-{component_index}",
                    "description": f"Test component - {self.generate_random_text(5, 10)}",
                    "project": project_key
                }
                tasks.append(self._api_call_async('POST', 'component', data=component_data))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0] and result[1]:
                    component_ids.append(result[1].get('id'))
                elif self.dry_run:
                    component_ids.append(f"component-{len(component_ids)}")

            self.logger.info(f"Created {len(component_ids)}/{count} components")

        self.created_components.extend(component_ids)
        return component_ids

    async def create_project_properties_async(self, project_keys: List[str], count: int) -> int:
        """Create project properties distributed across projects concurrently.

        Uses memory-efficient batching to avoid creating all tasks upfront.
        """
        self.logger.info(f"Creating {count} project properties (concurrency: {self.concurrency})...")

        created = 0
        failed = 0
        batch_size = self.concurrency * 2
        property_index = 0

        # Memory-efficient: process in batches instead of creating all tasks upfront
        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)
            current_batch_size = batch_end - batch_start

            # Generate tasks for this batch only
            tasks = []
            for _ in range(current_batch_size):
                property_index += 1
                project_key = project_keys[(property_index - 1) % len(project_keys)]
                property_key = f"{self.prefix.lower()}_property_{property_index}"

                property_value = {
                    "generatedBy": "jira-test-data-generator",
                    "runId": self.run_id,
                    "timestamp": datetime.now().isoformat(),
                    "index": property_index,
                    "category": random.choice(["config", "metadata", "settings", "cache"]),
                    "values": {
                        "enabled": random.choice([True, False]),
                        "threshold": random.randint(1, 100),
                        "mode": random.choice(["auto", "manual", "scheduled"]),
                        "description": self.generate_random_text(5, 15)
                    }
                }
                tasks.append(self._api_call_async('PUT', f'project/{project_key}/properties/{property_key}', data=property_value))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0]:
                    created += 1
                else:
                    failed += 1

            self.logger.info(f"Created {created}/{count} project properties ({failed} failed)")

        self.logger.info(f"Project properties complete: {created} created, {failed} failed")
        return created

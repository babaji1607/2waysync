import requests
import time
from typing import List, Optional
from utils.logger import setup_logger
from utils.models import Task, TaskStatus
from utils.config import Config

logger = setup_logger(__name__)

BASE_URL = "https://api.trello.com/1"


class TaskClient:
    """Trello Task Tracker client"""

    def __init__(
        self,
        api_key: str = None,
        api_token: str = None,
        board_id: str = None,
    ):
        """
        Initialize Trello client

        Args:
            api_key: Trello API key
            api_token: Trello API token
            board_id: Trello board ID
        """
        # Load from Config if not provided (runtime loading)
        self.api_key = api_key or Config.TRELLO_API_KEY
        self.api_token = api_token or Config.TRELLO_API_TOKEN
        self.board_id = board_id or Config.TRELLO_BOARD_ID
        self.list_mapping = Config.TRELLO_LIST_MAPPING
        
        # Log initialization for debugging
        logger.info(
            f"TaskClient initialized",
            extra={
                "extra_data": {
                    "board_id": self.board_id,
                    "has_api_key": bool(self.api_key),
                    "has_api_token": bool(self.api_token),
                }
            }
        )

    def _get_auth_params(self) -> dict:
        """Get authentication parameters"""
        return {"key": self.api_key, "token": self.api_token}

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        max_retries: int = 3,
    ) -> Optional[dict]:
        """
        Make HTTP request with retry logic and rate limit handling

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            data: Request data
            max_retries: Maximum number of retries

        Returns:
            Response JSON or None
        """
        url = f"{BASE_URL}/{endpoint}"
        params = self._get_auth_params()

        for attempt in range(max_retries):
            try:
                if method == "GET":
                    response = requests.get(url, params=params, timeout=10)
                elif method == "POST":
                    response = requests.post(url, params=params, json=data, timeout=10)
                elif method == "PUT":
                    response = requests.put(url, params=params, json=data, timeout=10)
                elif method == "DELETE":
                    response = requests.delete(url, params=params, timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                # Handle rate limiting
                if response.status_code == 429:
                    wait_time = int(response.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(
                        f"Rate limit hit, retrying in {wait_time}s",
                        extra={
                            "extra_data": {
                                "attempt": attempt,
                                "wait_time": wait_time,
                                "endpoint": endpoint,
                            }
                        },
                    )
                    time.sleep(wait_time)
                    continue

                if response.status_code == 401:
                    logger.error(
                        f"Trello authentication failed",
                        extra={"extra_data": {"endpoint": endpoint, "status": 401}},
                    )
                    raise Exception("Invalid Trello credentials")

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                logger.error(
                    f"Request failed: {str(e)}",
                    extra={
                        "extra_data": {
                            "method": method,
                            "endpoint": endpoint,
                            "attempt": attempt,
                            "error": str(e),
                        }
                    },
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None

        return None

    def get_all_tasks(self) -> List[Task]:
        """
        Fetch all tasks from Trello board

        Returns:
            List of Task objects
        """
        try:
            response = self._make_request("GET", f"boards/{self.board_id}/cards")
            if not response:
                logger.error("Failed to fetch tasks from Trello")
                return []

            tasks = []
            for card in response:
                try:
                    # Determine status from list
                    status = self._get_status_from_list_id(card.get("idList"))

                    # Extract lead_id from description (new format: "Lead ID: xxx")
                    lead_id = None
                    desc = card.get("desc", "")
                    
                    if desc:
                        # Try new format first: "Lead ID: value"
                        if "Lead ID:" in desc:
                            for line in desc.split("\n"):
                                if "Lead ID:" in line:
                                    lead_id = line.split(":", 1)[1].strip()
                                    break
                        # Fallback to old format: "value|..."
                        elif "|" in desc:
                            lead_id = desc.split("|")[0].strip()

                    task = Task(
                        id=card.get("id"),
                        title=card.get("name", ""),
                        status=status,
                        lead_id=lead_id,
                        notes=desc,
                        list_id=card.get("idList"),  # Store the list ID
                    )
                    tasks.append(task)
                except Exception as e:
                    logger.error(
                        f"Failed to parse task: {str(e)}",
                        extra={"extra_data": {"card": card, "error": str(e)}},
                    )
                    continue

            logger.info(
                f"Fetched {len(tasks)} tasks from Trello",
                extra={"extra_data": {"count": len(tasks)}},
            )
            return tasks

        except Exception as e:
            logger.error(
                f"Failed to fetch tasks: {str(e)}",
                extra={"extra_data": {"error": str(e)}},
            )
            return []

    def create_task(
        self,
        title: str,
        lead_id: str,
        status: str = "New",
        notes: Optional[str] = None,
        email: str = None,
        phone: str = None,
    ) -> Optional[str]:
        """
        Create a new task in Trello

        Args:
            title: Task title (Lead name)
            lead_id: Associated lead ID
            status: Task status (New, In Progress, Qualified, Done)
            notes: Optional notes
            email: Lead email
            phone: Lead phone

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            list_id = self.list_mapping.get(status, self.list_mapping.get("New"))

            # Format description with lead details
            description_lines = [
                f"Lead ID: {lead_id}",
                f"Email: {email}" if email else None,
                f"Phone: {phone}" if phone else None,
            ]
            # Filter out None values and join
            description_lines = [line for line in description_lines if line]
            description_lines.append(f"Notes: {notes}" if notes else "")
            
            description = "\n".join(description_lines)

            data = {
                "name": title,
                "idList": list_id,
                "desc": description,
            }

            response = self._make_request("POST", "cards", data)
            if response:
                task_id = response.get("id")
                logger.info(
                    f"Created card {task_id} for lead {lead_id}",
                    extra={"extra_data": {
                        "card_id": task_id, 
                        "lead_id": lead_id,
                        "email": email,
                        "status": status
                    }},
                )
                return task_id

            logger.error(
                f"Failed to create card for lead {lead_id}",
                extra={"extra_data": {"lead_id": lead_id}},
            )
            return None

        except Exception as e:
            logger.error(
                f"Failed to create card: {str(e)}",
                extra={"extra_data": {"lead_id": lead_id, "error": str(e)}},
            )
            return None

    def create_task_in_list(
        self, list_id: str, title: str, description: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a new task directly in a specific Trello list

        Args:
            list_id: Target Trello list ID
            title: Card title
            description: Card description

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            data = {
                "name": title,
                "idList": list_id,
                "desc": description or "",
            }

            response = self._make_request("POST", "cards", data)
            if response:
                card_id = response.get("id")
                logger.info(
                    f"Created card {card_id} in list {list_id}",
                    extra={"extra_data": {"card_id": card_id, "list_id": list_id}},
                )
                return card_id

            logger.error(f"Failed to create card in list {list_id}")
            return None

        except Exception as e:
            logger.error(
                f"Failed to create card: {str(e)}",
                extra={"extra_data": {"list_id": list_id, "error": str(e)}},
            )
            return None

    def update_task(
        self, task_id: str, status: Optional[str] = None, title: Optional[str] = None, notes: Optional[str] = None
    ) -> bool:
        """
        Update task status, title or notes

        Args:
            task_id: Task ID
            status: New status
            title: New title
            notes: New notes/description

        Returns:
            True if successful, False otherwise
        """
        try:
            data = {}

            if status:
                list_id = self.list_mapping.get(status, self.list_mapping.get("New"))
                data["idList"] = list_id

            if title:
                data["name"] = title
                
            if notes:
                data["desc"] = notes

            if not data:
                return True

            response = self._make_request("PUT", f"cards/{task_id}", data)
            if response:
                logger.info(
                    f"Updated task {task_id}",
                    extra={"extra_data": {"task_id": task_id, "updates": data}},
                )
                return True

            logger.error(
                f"Failed to update task {task_id}",
                extra={"extra_data": {"task_id": task_id}},
            )
            return False

        except Exception as e:
            logger.error(
                f"Failed to update task: {str(e)}",
                extra={"extra_data": {"task_id": task_id, "error": str(e)}},
            )
            return False

    def _get_status_from_list_id(self, list_id: str) -> str:
        """Map Trello list ID to task status"""
        for status, lid in self.list_mapping.items():
            if lid == list_id:
                return status
        return "New"  # Default status

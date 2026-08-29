"""
Pagination utilities for handling large lists efficiently.
Supports offset-based and cursor-based pagination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, List, Optional, Dict, Any
from math import ceil

T = TypeVar('T')


@dataclass
class PaginationParams:
    """Pagination parameters."""
    page: int = 1
    per_page: int = 20
    
    def __post_init__(self):
        """Validate pagination parameters."""
        if self.page < 1:
            self.page = 1
        if self.per_page < 1:
            self.per_page = 20
        if self.per_page > 100:
            self.per_page = 100
    
    @property
    def offset(self) -> int:
        """Calculate offset for database queries."""
        return (self.page - 1) * self.per_page
    
    @property
    def limit(self) -> int:
        """Get limit for database queries."""
        return self.per_page


@dataclass
class PaginatedResponse(Generic[T]):
    """Response model for paginated data."""
    items: List[T]
    total: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_previous: bool
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        per_page: int,
    ) -> PaginatedResponse[T]:
        """Create paginated response."""
        total_pages = ceil(total / per_page) if per_page > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "items": [item for item in self.items],
            "pagination": {
                "page": self.page,
                "per_page": self.per_page,
                "total": self.total,
                "total_pages": self.total_pages,
                "has_next": self.has_next,
                "has_previous": self.has_previous,
            }
        }


class CursorPaginationParams:
    """Cursor-based pagination for efficient large dataset navigation."""
    
    def __init__(self, cursor: Optional[str] = None, limit: int = 20):
        """Initialize cursor pagination."""
        self.cursor = cursor
        self.limit = min(limit, 100)  # Max 100 items per page
    
    def get_query_params(self) -> Dict[str, Any]:
        """Get parameters for database query."""
        return {
            "cursor": self.cursor,
            "limit": self.limit + 1,  # Fetch one extra to check if there's next page
        }


async def paginate_async(
    query_func,
    total_count: int,
    page: int = 1,
    per_page: int = 20,
) -> PaginatedResponse:
    """
    Helper function to paginate async query results.
    
    Args:
        query_func: Async function that returns items (must accept offset and limit)
        total_count: Total number of items
        page: Page number (1-indexed)
        per_page: Items per page
    
    Returns:
        PaginatedResponse with items and metadata
    """
    params = PaginationParams(page=page, per_page=per_page)
    
    items = await query_func(offset=params.offset, limit=params.limit)
    
    return PaginatedResponse.create(
        items=items,
        total=total_count,
        page=params.page,
        per_page=params.per_page,
    )

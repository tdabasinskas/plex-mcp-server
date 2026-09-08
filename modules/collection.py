from plexapi.collection import Collection # type: ignore
from typing import List, Dict, Any
from modules import mcp, connect_to_plex
from modules.smart_filter import describe_smart_filter
import os
from plexapi.exceptions import NotFound, BadRequest  # type: ignore
from mcp.types import ToolAnnotations  # type: ignore
import json

# Default page size when listing collection contents without an explicit limit,
# so large collections don't overflow a response.
DEFAULT_CONTENTS_PAGE = 200

@mcp.tool()
async def collection_list(library_name: str = None) -> str:
    """List all collections on the Plex server or in a specific library.
    
    Args:
        library_name: Optional name of the library to list collections from
    """
    try:
        plex = connect_to_plex()
        collections_data = []
        
        # If library_name is provided, only show collections from that library
        if library_name:
            try:
                library = plex.library.section(library_name)
                collections = library.collections()
                for collection in collections:
                    collection_info = {
                        "title": collection.title,
                        "summary": collection.summary,
                        "is_smart": collection.smart,
                        "ID": collection.ratingKey,
                        "items": collection.childCount
                    }
                    collections_data.append(collection_info)
                
                return json.dumps(collections_data, indent=4)
            except NotFound:
                return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
        
        # No library specified, get collections from all movie and show libraries
        movie_libraries = []
        show_libraries = []
        
        for section in plex.library.sections():
            if section.type == 'movie':
                movie_libraries.append(section)
            elif section.type == 'show':
                show_libraries.append(section)
        
        # Group collections by library
        libraries_collections = {}
        
        # Get movie collections
        for library in movie_libraries:
            lib_collections = []
            
            for collection in library.collections():
                collection_info = {
                    "title": collection.title,
                    "summary": collection.summary,
                    "is_smart": collection.smart,
                    "ID": collection.ratingKey,
                    "items": collection.childCount
                }
                # For smart collections, include the current filter definition
                if collection.smart:
                    try:
                        collection_info["smartFilter"] = collection.filters()
                    except Exception:
                        pass
                lib_collections.append(collection_info)
            
            libraries_collections[library.title] = {
                "type": "movie",
                "collections_count": len(lib_collections),
                "collections": lib_collections
            }
        
        # Get TV show collections
        for library in show_libraries:
            lib_collections = []
            
            for collection in library.collections():
                collection_info = {
                    "title": collection.title,
                    "summary": collection.summary,
                    "is_smart": collection.smart,
                    "ID": collection.ratingKey,
                    "items": collection.childCount
                }
                # For smart collections, include the current filter definition
                if collection.smart:
                    try:
                        collection_info["smartFilter"] = collection.filters()
                    except Exception:
                        pass
                lib_collections.append(collection_info)
            
            libraries_collections[library.title] = {
                "type": "show",
                "collections_count": len(lib_collections),
                "collections": lib_collections
            }
        
        return json.dumps(libraries_collections, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def collection_create(collection_title: str, library_name: str, item_titles: List[str] = None, item_ids: List[int] = None) -> str:
    """Create a new collection with specified items.
    
    Args:
        collection_title: Title for the new collection
        library_name: Name of the library to create the collection in
        item_titles: List of media titles to include in the collection (optional if item_ids is provided)
        item_ids: List of media IDs to include in the collection (optional if item_titles is provided)
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one item source is provided
        if (not item_titles or len(item_titles) == 0) and (not item_ids or len(item_ids) == 0):
            return json.dumps({"error": "Either item_titles or item_ids must be provided"}, indent=4)
        
        # Find the library
        try:
            library = plex.library.section(library_name)
        except NotFound:
            return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
        
        # Check if collection already exists
        try:
            existing_collection = next((c for c in library.collections() if c.title.lower() == collection_title.lower()), None)
            if existing_collection:
                return json.dumps({"error": f"Collection '{collection_title}' already exists in library '{library_name}'"}, indent=4)
        except Exception:
            pass  # If we can't check existing collections, proceed anyway
        
        # Find items to add to the collection
        items = []
        not_found = []
        
        # If we have item IDs, try to add by ID first
        if item_ids and len(item_ids) > 0:
            for item_id in item_ids:
                try:
                    # Try to fetch the item by ID
                    item = plex.fetchItem(item_id)
                    if item:
                        items.append(item)
                    else:
                        not_found.append(str(item_id))
                except Exception as e:
                    not_found.append(str(item_id))
        
        # If we have item titles, search for them
        if item_titles and len(item_titles) > 0:
            for title in item_titles:
                # Search for the media item
                search_results = library.search(title=title)
                
                if search_results:
                    # Check for exact title match (case insensitive)
                    exact_matches = [item for item in search_results if item.title.lower() == title.lower()]
                    
                    if exact_matches:
                        items.append(exact_matches[0])
                    else:
                        # No exact match, collect possible matches
                        possible_matches = []
                        for item in search_results:
                            possible_matches.append({
                                "title": item.title,
                                "id": item.ratingKey,
                                "type": item.type,
                                "year": item.year if hasattr(item, 'year') and item.year else None
                            })
                        
                        not_found.append({
                            "title": title,
                            "possible_matches": possible_matches
                        })
                else:
                    not_found.append(title)
        
        # If we have possible matches but no items to add, return the possible matches
        if not items and any(isinstance(item, dict) for item in not_found):
            possible_matches_response = []
            for item in not_found:
                if isinstance(item, dict) and "possible_matches" in item:
                    for match in item["possible_matches"]:
                        if match not in possible_matches_response:
                            possible_matches_response.append(match)
            
            return json.dumps({"Multiple Possible Matches Use ID":possible_matches_response}, indent=4)
        
        if not items:
            return json.dumps({"error": "No matching media items found for the collection"}, indent=4)
        
        # Create the collection
        collection = library.createCollection(title=collection_title, items=items)
        
        return json.dumps({
            "created": True,
            "title": collection.title,
            "id": collection.ratingKey,
            "library": library_name,
            "items_added": len(items),
            "items_not_found": [item for item in not_found if not isinstance(item, dict)]
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def collection_add_to(collection_title: str = None, collection_id: int = None, library_name: str = None, item_titles: List[str] = None, item_ids: List[int] = None) -> str:
    """Add items to an existing collection.
    
    Args:
        collection_title: Title of the collection to add to (optional if collection_id is provided)
        collection_id: ID of the collection to add to (optional if collection_title is provided)
        library_name: Name of the library containing the collection (required if using collection_title)
        item_titles: List of media titles to add to the collection (optional if item_ids is provided)
        item_ids: List of media IDs to add to the collection (optional if item_titles is provided)
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not collection_id and not collection_title:
            return json.dumps({"error": "Either collection_id or collection_title must be provided"}, indent=4)
        
        # Validate that at least one item source is provided
        if (not item_titles or len(item_titles) == 0) and (not item_ids or len(item_ids) == 0):
            return json.dumps({"error": "Either item_titles or item_ids must be provided"}, indent=4)
        
        # Find the collection
        collection = None
        library = None
        
        # If collection_id is provided, use it to directly fetch the collection
        if collection_id:
            try:
                # Try fetching by ratingKey first
                try:
                    collection = plex.fetchItem(collection_id)
                except:
                    # If that fails, try finding by key in all libraries
                    collection = None
                    for section in plex.library.sections():
                        if section.type in ['movie', 'show']:
                            try:
                                for c in section.collections():
                                    if c.ratingKey == collection_id:
                                        collection = c
                                        library = section
                                        break
                                if collection is not None:
                                    break
                            except:
                                continue
                
                if collection is None:
                    return json.dumps({"error": f"Collection with ID '{collection_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching collection by ID: {str(e)}"}, indent=4)
        else:
            # If we're searching by title
            if not library_name:
                return json.dumps({"error": "Library name is required when adding items by collection title"}, indent=4)
            
            # Find the library
            try:
                library = plex.library.section(library_name)
            except NotFound:
                return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
            
            # Find matching collections
            matching_collections = [c for c in library.collections() if c.title.lower() == collection_title.lower()]
            
            if not matching_collections:
                return json.dumps({"error": f"Collection '{collection_title}' not found in library '{library_name}'"}, indent=4)
            
            # If multiple matching collections, return list of matches with IDs
            if len(matching_collections) > 1:
                matches = []
                for c in matching_collections:
                    matches.append({
                        "title": c.title,
                        "id": c.ratingKey,
                        "library": library_name,
                        "item_count": c.childCount if hasattr(c, 'childCount') else len(c.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps(matches, indent=4)
            
            collection = matching_collections[0]
        
        # Find items to add
        items_to_add = []
        not_found = []
        already_in_collection = []
        current_items = collection.items()
        current_item_ids = [item.ratingKey for item in current_items]
        
        # If we have item IDs, try to add by ID first
        if item_ids and len(item_ids) > 0:
            for item_id in item_ids:
                try:
                    # Try to fetch the item by ID
                    item = plex.fetchItem(item_id)
                    if item:
                        if item.ratingKey in current_item_ids:
                            already_in_collection.append(str(item_id))
                        else:
                            items_to_add.append(item)
                    else:
                        not_found.append(str(item_id))
                except Exception as e:
                    not_found.append(str(item_id))
        
        # If we have item titles, search for them with exact matching
        if item_titles and len(item_titles) > 0:
            if not library:
                # This could happen if we found the collection by ID
                # Try to determine which library the collection belongs to
                for section in plex.library.sections():
                    if section.type == 'movie' or section.type == 'show':
                        try:
                            for c in section.collections():
                                if c.ratingKey == collection.ratingKey:
                                    library = section
                                    break
                            if library:
                                break
                        except:
                            continue
                
                if not library:
                    return json.dumps({"error": "Could not determine which library to search in"}, indent=4)
            
            for title in item_titles:
                # Search for the media item with exact matching
                search_results = library.search(title=title)
                
                if search_results:
                    # Check for exact title match (case insensitive)
                    exact_matches = [item for item in search_results if item.title.lower() == title.lower()]
                    
                    if exact_matches:
                        item = exact_matches[0]
                        if item.ratingKey in current_item_ids:
                            already_in_collection.append(title)
                        else:
                            items_to_add.append(item)
                    else:
                        # No exact match, collect possible matches
                        possible_matches = []
                        for item in search_results:
                            possible_matches.append({
                                "title": item.title,
                                "id": item.ratingKey,
                                "type": item.type,
                                "year": item.year if hasattr(item, 'year') and item.year else None
                            })
                        
                        not_found.append({
                            "title": title,
                            "possible_matches": possible_matches
                        })
                else:
                    not_found.append(title)
        
        # If we have possible matches but no items to add, return the possible matches
        if not items_to_add and any(isinstance(item, dict) for item in not_found):
            possible_matches_response = []
            for item in not_found:
                if isinstance(item, dict) and "possible_matches" in item:
                    for match in item["possible_matches"]:
                        if match not in possible_matches_response:
                            possible_matches_response.append(match)
            
            return json.dumps(possible_matches_response, indent=4)
        
        # If no items to add and no possible matches
        if not items_to_add and not already_in_collection:
            return json.dumps({"error": "No matching media items found to add to the collection"}, indent=4)
        
        # Add items to the collection
        if items_to_add:
            collection.addItems(items_to_add)
        
        return json.dumps({
            "added": True,
            "title": collection.title,
            "items_added": [item.title for item in items_to_add],
            "items_already_in_collection": already_in_collection,
            "items_not_found": [item for item in not_found if not isinstance(item, dict)],
            "total_items": len(collection.items())
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def collection_remove_from(collection_title: str = None, collection_id: int = None, library_name: str = None, item_titles: List[str] = None) -> str:
    """Remove items from a collection.
    
    Args:
        collection_title: Title of the collection to remove from (optional if collection_id is provided)
        collection_id: ID of the collection to remove from (optional if collection_title is provided)
        library_name: Name of the library containing the collection (required if using collection_title)
        item_titles: List of media titles to remove from the collection
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not collection_id and not collection_title:
            return json.dumps({"error": "Either collection_id or collection_title must be provided"}, indent=4)
        
        if not item_titles or len(item_titles) == 0:
            return json.dumps({"error": "At least one item title must be provided to remove"}, indent=4)
        
        # Find the collection
        collection = None
        
        # If collection_id is provided, use it to directly fetch the collection
        if collection_id:
            try:
                # Try fetching by ratingKey first
                try:
                    collection = plex.fetchItem(collection_id)
                except:
                    # If that fails, try finding by key in all libraries
                    collection = None
                    for section in plex.library.sections():
                        if section.type in ['movie', 'show']:
                            try:
                                for c in section.collections():
                                    if c.ratingKey == collection_id:
                                        collection = c
                                        break
                                if collection is not None:
                                    break
                            except:
                                continue
                
                if collection is None:
                    return json.dumps({"error": f"Collection with ID '{collection_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching collection by ID: {str(e)}"}, indent=4)
        else:
            # If we get here, we're searching by title
            if not library_name:
                return json.dumps({"error": "Library name is required when removing items by collection title"}, indent=4)
            
            # Find the library
            try:
                library = plex.library.section(library_name)
            except NotFound:
                return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
            
            # Find matching collections
            matching_collections = [c for c in library.collections() if c.title.lower() == collection_title.lower()]
            
            if not matching_collections:
                return json.dumps({"error": f"Collection '{collection_title}' not found in library '{library_name}'"}, indent=4)
            
            # If multiple matching collections, return list of matches with IDs
            if len(matching_collections) > 1:
                matches = []
                for c in matching_collections:
                    matches.append({
                        "title": c.title,
                        "id": c.ratingKey,
                        "library": library_name,
                        "item_count": c.childCount if hasattr(c, 'childCount') else len(c.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps(matches, indent=4)
            
            collection = matching_collections[0]
        
        # Get current items in the collection
        collection_items = collection.items()
        
        # Find items to remove
        items_to_remove = []
        not_found = []
        
        for title in item_titles:
            found = False
            for item in collection_items:
                if item.title.lower() == title.lower():
                    items_to_remove.append(item)
                    found = True
                    break
            if not found:
                not_found.append(title)
        
        if not items_to_remove:
            # No items found to remove, return the current collection contents
            current_items = []
            for item in collection_items:
                current_items.append({
                    "title": item.title,
                    "type": item.type,
                    "id": item.ratingKey
                })
            
            return json.dumps({
                "error": "No matching items found in the collection to remove",
                "collection_title": collection.title,
                "collection_id": collection.ratingKey,
                "current_items": current_items
            }, indent=4)
        
        # Remove items from the collection
        collection.removeItems(items_to_remove)
        
        return json.dumps({
            "removed": True,
            "title": collection.title,
            "items_removed": [item.title for item in items_to_remove],
            "items_not_found": not_found,
            "remaining_items": len(collection.items())
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def collection_delete(collection_title: str = None, collection_id: int = None, library_name: str = None) -> str:
    """Delete a collection.
    
    Args:
        collection_title: Title of the collection to delete (optional if collection_id is provided)
        collection_id: ID of the collection to delete (optional if collection_title is provided)
        library_name: Name of the library containing the collection (required if using collection_title)
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not collection_id and not collection_title:
            return json.dumps({"error": "Either collection_id or collection_title must be provided"}, indent=4)
        
        # If collection_id is provided, use it to directly fetch the collection
        if collection_id:
            try:
                # Try fetching by ratingKey first
                try:
                    collection = plex.fetchItem(collection_id)
                except:
                    # If that fails, try finding by key in all libraries
                    collection = None
                    for section in plex.library.sections():
                        if section.type in ['movie', 'show']:
                            try:
                                for c in section.collections():
                                    if c.ratingKey == collection_id:
                                        collection = c
                                        break
                                if collection is not None:
                                    break
                            except:
                                continue
                
                if collection is None:
                    return json.dumps({"error": f"Collection with ID '{collection_id}' not found"}, indent=4)
                
                # Get the collection title to return in the message
                collection_title_to_return = collection.title
                
                # Delete the collection
                collection.delete()
                
                # Return a simple object with the result
                return json.dumps({
                    "deleted": True,
                    "title": collection_title_to_return
                }, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching collection by ID: {str(e)}"}, indent=4)
        
        # If we get here, we're searching by title
        if not library_name:
            return json.dumps({"error": "Library name is required when deleting by collection title"}, indent=4)
        
        # Find the library
        try:
            library = plex.library.section(library_name)
        except NotFound:
            return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
        
        # Find matching collections
        matching_collections = [c for c in library.collections() if c.title.lower() == collection_title.lower()]
        
        if not matching_collections:
            return json.dumps({"error": f"Collection '{collection_title}' not found in library '{library_name}'"}, indent=4)
        
        # If multiple matching collections, return list of matches with IDs
        if len(matching_collections) > 1:
            matches = []
            for c in matching_collections:
                matches.append({
                    "title": c.title,
                    "id": c.ratingKey,
                    "library": library_name,
                    "item_count": c.childCount if hasattr(c, 'childCount') else len(c.items())
                })
            
            # Return as a direct array like playlist_list
            return json.dumps(matches, indent=4)
        
        collection = matching_collections[0]
        collection_title_to_return = collection.title
        
        # Delete the collection
        collection.delete()
        
        # Return a simple object with the result
        return json.dumps({
            "deleted": True,
            "title": collection_title_to_return
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def collection_edit(collection_title: str = None, collection_id: int = None, library_name: str = None, 
                      new_title: str = None, new_sort_title: str = None,
                      new_summary: str = None, new_content_rating: str = None,
                      new_labels: List[str] = None, add_labels: List[str] = None,
                      remove_labels: List[str] = None,
                      poster_path: str = None, poster_url: str = None,
                      background_path: str = None, background_url: str = None,
                      new_advanced_settings: Dict[str, Any] = None) -> str:
    """Comprehensively edit a collection's attributes.
    
    Args:
        collection_title: Title of the collection to edit (optional if collection_id is provided)
        collection_id: ID of the collection to edit (optional if collection_title is provided)
        library_name: Name of the library containing the collection (required if using collection_title)
        new_title: New title for the collection
        new_sort_title: New sort title for the collection
        new_summary: New summary/description for the collection
        new_content_rating: New content rating (e.g., PG-13, R, etc.)
        new_labels: Set completely new labels (replaces existing)
        add_labels: Labels to add to existing ones
        remove_labels: Labels to remove from existing ones
        poster_path: Path to a new poster image file
        poster_url: URL to a new poster image
        background_path: Path to a new background/art image file
        background_url: URL to a new background/art image
        new_advanced_settings: Dictionary of advanced settings to apply
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not collection_id and not collection_title:
            return json.dumps({"error": "Either collection_id or collection_title must be provided"}, indent=4)
        
        # Find the collection
        collection = None
        
        # If collection_id is provided, use it to directly fetch the collection
        if collection_id:
            try:
                # Try fetching by ratingKey first
                try:
                    collection = plex.fetchItem(collection_id)
                except:
                    # If that fails, try finding by key in all libraries
                    collection = None
                    for section in plex.library.sections():
                        if section.type in ['movie', 'show']:
                            try:
                                for c in section.collections():
                                    if c.ratingKey == collection_id:
                                        collection = c
                                        break
                                if collection is not None:
                                    break
                            except:
                                continue
                
                if collection is None:
                    return json.dumps({"error": f"Collection with ID '{collection_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching collection by ID: {str(e)}"}, indent=4)
        else:
            # If we get here, we're searching by title
            if not library_name:
                return json.dumps({"error": "Library name is required when editing by collection title"}, indent=4)
            
            # Find the library
            try:
                library = plex.library.section(library_name)
            except NotFound:
                return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
            
            # Find matching collections
            matching_collections = [c for c in library.collections() if c.title.lower() == collection_title.lower()]
            
            if not matching_collections:
                return json.dumps({"error": f"Collection '{collection_title}' not found in library '{library_name}'"}, indent=4)
            
            # If multiple matching collections, return list of matches with IDs
            if len(matching_collections) > 1:
                matches = []
                for c in matching_collections:
                    matches.append({
                        "title": c.title,
                        "id": c.ratingKey,
                        "library": library_name,
                        "item_count": c.childCount if hasattr(c, 'childCount') else len(c.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps(matches, indent=4)
            
            collection = matching_collections[0]
        
        # Track changes
        changes = []
        
        # Edit basic attributes
        edit_params = {}
        
        if new_title is not None and new_title != collection.title:
            edit_params['title'] = new_title
            changes.append(f"title to '{new_title}'")
        
        if new_sort_title is not None:
            current_sort = getattr(collection, 'titleSort', '')
            if new_sort_title != current_sort:
                edit_params['titleSort'] = new_sort_title
                changes.append(f"sort title to '{new_sort_title}'")
        
        if new_summary is not None:
            current_summary = getattr(collection, 'summary', '')
            if new_summary != current_summary:
                edit_params['summary'] = new_summary
                changes.append("summary")
        
        if new_content_rating is not None:
            current_rating = getattr(collection, 'contentRating', '')
            if new_content_rating != current_rating:
                edit_params['contentRating'] = new_content_rating
                changes.append(f"content rating to '{new_content_rating}'")
        
        # Apply the basic edits if any parameters were set
        if edit_params:
            collection.edit(**edit_params)
        
        # Handle labels
        current_labels = getattr(collection, 'labels', [])
        
        if new_labels is not None:
            # Replace all labels
            collection.removeLabel(current_labels)
            if new_labels:
                collection.addLabel(new_labels)
            changes.append("labels completely replaced")
        else:
            # Handle adding and removing individual labels
            if add_labels:
                for label in add_labels:
                    if label not in current_labels:
                        collection.addLabel(label)
                changes.append(f"added labels: {', '.join(add_labels)}")
            
            if remove_labels:
                for label in remove_labels:
                    if label in current_labels:
                        collection.removeLabel(label)
                changes.append(f"removed labels: {', '.join(remove_labels)}")
        
        # Handle artwork
        if poster_path:
            collection.uploadPoster(filepath=poster_path)
            changes.append("poster (from file)")
        elif poster_url:
            collection.uploadPoster(url=poster_url)
            changes.append("poster (from URL)")
        
        if background_path:
            collection.uploadArt(filepath=background_path)
            changes.append("background art (from file)")
        elif background_url:
            collection.uploadArt(url=background_url)
            changes.append("background art (from URL)")
        
        # Handle advanced settings
        if new_advanced_settings:
            for key, value in new_advanced_settings.items():
                try:
                    setattr(collection, key, value)
                    changes.append(f"advanced setting '{key}'")
                except Exception as setting_error:
                    return json.dumps({
                        "error": f"Error setting advanced parameter '{key}': {str(setting_error)}"
                    }, indent=4)
        
        if not changes:
            return json.dumps({"updated": False, "message": "No changes made to the collection"}, indent=4)
        
        # Get the collection title for the response (use new_title if it was changed)
        collection_title_to_return = new_title if new_title else collection.title
        
        return json.dumps({
            "updated": True,
            "title": collection_title_to_return,
            "changes": changes
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)


def _resolve_collection(plex, collection_title=None, collection_id=None, library_name=None):
    """Resolve a collection by id, or by title within a library.

    Returns a tuple (collection, error_response). On success, collection is the
    matched Collection and error_response is None. On failure or ambiguity,
    collection is None and error_response is a JSON string ready to return.
    """
    if not collection_id and not collection_title:
        return None, json.dumps({"error": "Either collection_id or collection_title must be provided"}, indent=4)

    # Fetch directly by id when provided
    if collection_id:
        try:
            try:
                collection = plex.fetchItem(collection_id)
            except Exception:
                # Fall back to scanning movie/show library collections by ratingKey
                collection = None
                for section in plex.library.sections():
                    if section.type in ['movie', 'show']:
                        try:
                            collection = next((c for c in section.collections() if c.ratingKey == collection_id), None)
                        except Exception:
                            continue
                        if collection is not None:
                            break
            if collection is None:
                return None, json.dumps({"error": f"Collection with ID '{collection_id}' not found"}, indent=4)
            return collection, None
        except Exception as e:
            return None, json.dumps({"error": f"Error fetching collection by ID: {str(e)}"}, indent=4)

    # Otherwise match by title within a specific library
    if not library_name:
        return None, json.dumps({"error": "Library name is required when resolving by collection title"}, indent=4)
    try:
        library = plex.library.section(library_name)
    except NotFound:
        return None, json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)

    matching = [c for c in library.collections() if c.title.lower() == collection_title.lower()]
    if not matching:
        return None, json.dumps({"error": f"Collection '{collection_title}' not found in library '{library_name}'"}, indent=4)
    if len(matching) > 1:
        # Ambiguous title: return the candidates so the caller can pick an id
        matches = [{"title": c.title, "id": c.ratingKey, "library": library_name} for c in matching]
        return None, json.dumps(matches, indent=4)
    return matching[0], None


@mcp.tool()
async def collection_create_smart(collection_title: str, library_name: str, filters: dict = None,
                                  sort: str = None, limit: int = None, libtype: str = None,
                                  summary: str = None) -> str:
    """Create a smart collection that Plex keeps auto-populated from a library search.

    Unlike collection_create (a fixed list of items), a smart collection is a saved filter
    scoped to a single library section. Use library_get_smart_filter_options first to
    discover the available filter fields, operators, sort fields, and valid values.

    Args:
        collection_title: Title for the new smart collection
        library_name: Library section the collection is built from (smart collections are single-section)
        filters: Advanced filters as a dict, e.g. {"genre": "Comedy", "year>>": 2000, "unwatched": true}.
            Append an operator suffix (see library_get_smart_filter_options) to a field for
            comparisons. No suffix on a string field means 'contains', not exact match:
            "title" matches substrings, "title=" is exact.
        sort: Sort field(s), e.g. "addedAt:desc" or "year:asc". Comma-separate multiple fields.
        limit: Maximum number of items in the collection
        libtype: Content type to filter (movie, show, season, episode, artist, album, track, photo).
            Defaults to the section's type - note this is 'episode' for TV libraries and 'track' for
            music, so set libtype='show'/'artist' if you want whole shows/artists.
        summary: Optional description for the collection
    """
    try:
        plex = connect_to_plex()
        try:
            library = plex.library.section(library_name)
        except NotFound:
            return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)

        # Refuse to duplicate an existing collection title in this library
        try:
            existing = next((c for c in library.collections() if c.title.lower() == collection_title.lower()), None)
            if existing:
                return json.dumps({"status": "error", "message": f"Collection '{collection_title}' already exists in library '{library_name}'"}, indent=4)
        except Exception:
            pass  # If we can't check existing collections, proceed anyway

        try:
            collection = library.createCollection(
                title=collection_title,
                smart=True,
                filters=filters,
                sort=sort,
                limit=limit,
                libtype=libtype
            )
        except BadRequest as e:
            return json.dumps({"status": "error", "message": f"Invalid smart collection definition: {str(e)}"}, indent=4)

        # Apply an optional summary after creation
        if summary:
            try:
                collection.editSummary(summary)
            except Exception:
                pass

        # Reload so item_count reflects what the filter actually matched, not a
        # stale value from creation - verify this count looks right for the filter.
        try:
            collection.reload()
        except Exception:
            pass

        return json.dumps({
            "status": "success",
            "message": f"Smart collection '{collection_title}' created successfully",
            "data": {
                "title": collection.title,
                "id": collection.ratingKey,
                "smart": True,
                "library": library.title,
                "item_count": collection.childCount if hasattr(collection, 'childCount') else None
            }
        }, indent=4)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=4)


@mcp.tool()
async def collection_edit_smart_filters(collection_title: str = None, collection_id: int = None,
                                        library_name: str = None, filters: dict = None,
                                        sort: str = None, limit: int = None, libtype: str = None) -> str:
    """Update the filter definition of an existing smart collection.

    This replaces the smart collection's search criteria; Plex re-evaluates it immediately.
    Only works on smart collections - use collection_edit for a regular collection's attributes.

    Args:
        collection_title: Title of the smart collection to edit (optional if collection_id is provided)
        collection_id: ID of the smart collection to edit (optional if collection_title is provided)
        library_name: Name of the library containing the collection (required if using collection_title)
        filters: New advanced filters as a dict, e.g. {"genre": "Drama", "year>>": 2010}.
            See library_get_smart_filter_options for available fields, operators, and values.
            No suffix on a string field means 'contains': "title=" is the exact match.
        sort: New sort field(s), e.g. "addedAt:desc"
        limit: New maximum number of items in the collection
        libtype: Content type to filter (movie, show, season, episode, artist, album, track, photo)
    """
    try:
        plex = connect_to_plex()

        collection, error_response = _resolve_collection(plex, collection_title, collection_id, library_name)
        if error_response is not None:
            return error_response

        if not getattr(collection, 'smart', False):
            return json.dumps({
                "status": "error",
                "message": f"Collection '{collection.title}' is not a smart collection; its filters cannot be edited"
            }, indent=4)

        try:
            collection.updateFilters(libtype=libtype, limit=limit, sort=sort, filters=filters)
        except BadRequest as e:
            return json.dumps({"status": "error", "message": f"Invalid smart collection filters: {str(e)}"}, indent=4)

        collection.reload()
        return json.dumps({
            "status": "success",
            "message": f"Smart collection '{collection.title}' filters updated successfully",
            "data": {
                "title": collection.title,
                "id": collection.ratingKey,
                "item_count": collection.childCount if hasattr(collection, 'childCount') else None
            }
        }, indent=4)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=4)


def get_collection_contents(collection, offset=0, limit=None, include_items=True):
    """Helper: build a collection's paginated items plus (for smart collections) its filter definition.

    Pagination is done server-side (Plex container params), so only the requested page is fetched.
    When include_items is False, no items are fetched - only metadata and the smart filter.
    Mirrors get_playlist_contents so the two readbacks stay consistent.
    """
    try:
        # Capture the filter URI before reloading: a collection's key addresses
        # its /children representation, which need not carry 'content'.
        raw_content = getattr(collection, 'content', None)

        # Refresh so totalItems (childCount) is current
        try:
            collection.reload()
        except Exception:
            pass
        total = getattr(collection, 'childCount', None)

        is_smart = bool(getattr(collection, 'smart', False))

        collection_info = {
            "title": collection.title,
            "id": collection.ratingKey,
            "key": collection.key,
            "type": collection.subtype if hasattr(collection, 'subtype') else None,
            "smart": is_smart,
            "summary": collection.summary if hasattr(collection, 'summary') else None,
            "totalItems": total
        }
        # Include the smart filter definition so it can be read back before editing
        if is_smart:
            collection_info.update(describe_smart_filter(collection, raw_content))

        # Filter-only mode: skip fetching items entirely
        if not include_items:
            collection_info["itemsIncluded"] = False
            return json.dumps(collection_info, indent=4)

        # Fetch just the requested page of items (server-side pagination)
        page_size = limit if limit is not None else DEFAULT_CONTENTS_PAGE
        offset = max(0, offset or 0)
        items = collection.fetchItems(f'{collection.key}/children', container_start=offset, container_size=page_size)

        collection_items = []
        for i, item in enumerate(items):
            position = offset + i + 1
            item_data = {
                "title": item.title,
                "type": item.type,
                "position": position,
                "ratingKey": item.ratingKey,
                "addedAt": item.addedAt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(item, 'addedAt') and item.addedAt else None,
                "thumb": item.thumb if hasattr(item, 'thumb') else None
            }

            # Add media-type specific fields
            if item.type == 'movie':
                item_data["year"] = item.year if hasattr(item, 'year') else None
            elif item.type == 'show':
                item_data["year"] = item.year if hasattr(item, 'year') else None
            elif item.type == 'episode':
                item_data["show"] = item.grandparentTitle if hasattr(item, 'grandparentTitle') else None
                item_data["season"] = item.parentTitle if hasattr(item, 'parentTitle') else None
                item_data["seasonNumber"] = item.parentIndex if hasattr(item, 'parentIndex') else None
                item_data["episodeNumber"] = item.index if hasattr(item, 'index') else None
            elif item.type == 'artist':
                pass
            elif item.type == 'album':
                item_data["artist"] = item.parentTitle if hasattr(item, 'parentTitle') else None
                item_data["year"] = item.year if hasattr(item, 'year') else None
            elif item.type == 'track':
                item_data["artist"] = item.grandparentTitle if hasattr(item, 'grandparentTitle') else None
                item_data["album"] = item.parentTitle if hasattr(item, 'parentTitle') else None
                item_data["albumArtist"] = item.originalTitle if hasattr(item, 'originalTitle') else None

            collection_items.append(item_data)

        returned = len(collection_items)
        if total is not None:
            has_more = offset + returned < total
        else:
            has_more = returned == page_size

        collection_info.update({
            "offset": offset,
            "limit": page_size,
            "returnedCount": returned,
            "hasMore": has_more,
            "items": collection_items
        })

        return json.dumps(collection_info, indent=4)
    except Exception as e:
        return json.dumps({"error": f"Error formatting collection contents: {str(e)}"}, indent=4)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def collection_get_contents(collection_title: str = None, collection_id: int = None,
                                  library_name: str = None, limit: int = None, offset: int = 0,
                                  include_items: bool = True) -> str:
    """Get the contents of a collection, with pagination, including the filter for a smart collection.

    This is the collection analog of playlist_get_contents: it returns one page of the collection's
    items and, when the collection is smart, `smartFilter` (the saved search that populates it, in
    the form the create/edit tools accept) plus `smartFilterRaw` (the same filter as Plex stores it
    on the wire). Compare the two when verifying what a write actually saved: the wire form spells
    operators differently, so `title=` in `smartFilter` is `title==` in `smartFilterRaw` and both
    mean an exact match. If the filter can't be read, `smartFilter` carries an `error` explaining
    why rather than going missing. The response includes `totalItems`, `offset`, `limit`,
    `returnedCount`, and `hasMore`; page through by increasing `offset`.

    Args:
        collection_title: Title of the collection (optional if collection_id is provided)
        collection_id: ID of the collection (optional if collection_title is provided)
        library_name: Name of the library containing the collection (required if using collection_title)
        limit: Maximum number of items to return in this page (defaults to 200)
        offset: Number of items to skip before this page (for paging; default 0)
        include_items: When False, skip the item list entirely and return only metadata and, for a
            smart collection, its `smartFilter`. Use this to read a large collection's filter cheaply.
    """
    try:
        plex = connect_to_plex()

        collection, error_response = _resolve_collection(plex, collection_title, collection_id, library_name)
        if error_response is not None:
            return error_response

        return get_collection_contents(collection, offset=offset, limit=limit, include_items=include_items)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error getting collection contents: {str(e)}"}, indent=4)

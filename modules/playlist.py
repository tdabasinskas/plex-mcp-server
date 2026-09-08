from modules import mcp, connect_to_plex
from modules.smart_filter import describe_smart_filter
from typing import List
from plexapi.playlist import Playlist # type: ignore
from plexapi.exceptions import NotFound, BadRequest  # type: ignore
from mcp.types import ToolAnnotations  # type: ignore
import os
import requests
import base64
import json

# Default page size when listing playlist/collection contents without an explicit limit,
# so large (potentially hundreds of thousands of items) playlists don't overflow a response.
DEFAULT_CONTENTS_PAGE = 200

# Functions for playlists and collections
@mcp.tool()
async def playlist_list(library_name: str = None, content_type: str = None) -> str:
    """List all playlists on the Plex server.
    
    Args:
        library_name: Optional library name to filter playlists from
        content_type: Optional content type to filter playlists (audio, video, photo)
    """
    try:
        plex = connect_to_plex()
        playlists = []
        
        # Filter by content type if specified
        if content_type:
            valid_types = ["audio", "video", "photo"]
            if content_type.lower() not in valid_types:
                return json.dumps({"error": f"Invalid content type. Valid types are: {', '.join(valid_types)}"}, indent=4)
            playlists = plex.playlists(playlistType=content_type.lower())
        else:
            playlists = plex.playlists()
        
        # Filter by library if specified
        if library_name:
            try:
                library = plex.library.section(library_name)
                # Use the section's playlists method directly
                if content_type:
                    playlists = library.playlists(playlistType=content_type.lower())
                else:
                    playlists = library.playlists()
            except NotFound:
                return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)
        
        # Format playlist data (lightweight version - no items)
        playlist_data = []
        for playlist in playlists:
            try:
                playlist_data.append({
                    "title": playlist.title,
                    "key": playlist.key,
                    "ratingKey": playlist.ratingKey,
                    "type": playlist.playlistType,
                    "summary": playlist.summary if hasattr(playlist, 'summary') else "",
                    "duration": playlist.duration if hasattr(playlist, 'duration') else None,
                    "item_count": playlist.leafCount if hasattr(playlist, 'leafCount') else None
                })
            except Exception as item_error:
                # If there's an error with a specific playlist, include error info
                playlist_data.append({
                    "title": getattr(playlist, 'title', 'Unknown'),
                    "key": getattr(playlist, 'key', 'Unknown'),
                    "error": str(item_error)
                })
        
        return json.dumps(playlist_data, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def playlist_create(playlist_title: str, item_titles: List[str], library_name: str = None, summary: str = None) -> str:
    """Create a new playlist with specified items.
    
    Args:
        playlist_title: Title for the new playlist
        item_titles: List of media titles to include in the playlist
        library_name: Optional library name to limit search to
        summary: Optional summary description for the playlist
    """
    try:
        plex = connect_to_plex()
        items = []
        
        # Search for items in all libraries or specific library
        for title in item_titles:
            found = False
            search_scope = plex.library.section(library_name) if library_name else plex.library
            
            # Search for the item
            search_results = search_scope.search(title=title)
            
            if search_results:
                items.append(search_results[0])
                found = True
            
            if not found:
                return json.dumps({"status": "error", "message": f"Item '{title}' not found"}, indent=4)
        
        if not items:
            return json.dumps({"status": "error", "message": "No items found for the playlist"}, indent=4)
        
        # Create the playlist
        playlist = plex.createPlaylist(title=playlist_title, items=items, summary=summary)
        
        return json.dumps({
            "status": "success", 
            "message": f"Playlist '{playlist_title}' created successfully",
            "data": {
                "title": playlist.title,
                "key": playlist.key,
                "ratingKey": playlist.ratingKey,
                "item_count": len(items)
            }
        }, indent=4)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=4)

@mcp.tool()
async def playlist_edit(playlist_title: str = None, playlist_id: int = None, new_title: str = None, new_summary: str = None) -> str:
    """Edit a playlist's details such as title and summary.
    
    Args:
        playlist_title: Title of the playlist to edit (optional if playlist_id is provided)
        playlist_id: ID of the playlist to edit (optional if playlist_title is provided)
        new_title: Optional new title for the playlist
        new_summary: Optional new summary for the playlist
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)
        
        # Find the playlist
        playlist = None
        original_title = None
        
        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)
                
                if playlist is None:
                    return json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
                original_title = playlist.title
            except Exception as e:
                return json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)
        else:
            # Search by title
            playlists = plex.playlists()
            matching_playlists = [p for p in playlists if p.title.lower() == playlist_title.lower()]
            
            if not matching_playlists:
                return json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)
            
            # If multiple matching playlists, return list of matches with IDs
            if len(matching_playlists) > 1:
                matches = []
                for p in matching_playlists:
                    matches.append({
                        "title": p.title,
                        "id": p.ratingKey,
                        "type": p.playlistType,
                        "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps(matches, indent=4)
                
            playlist = matching_playlists[0]
            original_title = playlist.title
        
        # Track changes
        changes = []
        
        # Update title if provided
        if new_title and new_title != playlist.title:
            playlist.edit(title=new_title)
            changes.append(f"title from '{original_title}' to '{new_title}'")
        
        # Update summary if provided
        if new_summary is not None:  # Allow empty summaries
            current_summary = playlist.summary if hasattr(playlist, 'summary') else ""
            if new_summary != current_summary:
                playlist.edit(summary=new_summary)
                changes.append("summary")
        
        if not changes:
            return json.dumps({
                "updated": False,
                "title": playlist.title,
                "message": "No changes made to the playlist"
            }, indent=4)
            
        return json.dumps({
            "updated": True,
            "title": new_title or playlist.title,
            "changes": changes
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def playlist_upload_poster(playlist_title: str = None, playlist_id: int = None, poster_url: str = None, poster_filepath: str = None) -> str:
    """Upload a poster image for a playlist.
    
    Args:
        playlist_title: Title of the playlist to set poster for (optional if playlist_id is provided)
        playlist_id: ID of the playlist to set poster for (optional if playlist_title is provided)
        poster_url: URL to an image to use as poster
        poster_filepath: Local file path to an image to use as poster
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)
        
        # Check that at least one poster source is provided
        if not poster_url and not poster_filepath:
            return json.dumps({"error": "Either poster_url or poster_filepath must be provided"}, indent=4)
        
        # Find the playlist
        playlist = None
        
        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)
                
                if playlist is None:
                    return json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)
        else:
            # Search by title
            playlists = plex.playlists()
            matching_playlists = [p for p in playlists if p.title.lower() == playlist_title.lower()]
            
            if not matching_playlists:
                return json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)
            
            # If multiple matching playlists, return list of matches with IDs
            if len(matching_playlists) > 1:
                matches = []
                for p in matching_playlists:
                    matches.append({
                        "title": p.title,
                        "id": p.ratingKey,
                        "type": p.playlistType,
                        "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps(matches, indent=4)
                
            playlist = matching_playlists[0]
        
        # Upload from URL
        if poster_url:
            try:
                response = requests.get(poster_url)
                if response.status_code != 200:
                    return json.dumps({"error": f"Failed to download image from URL: {response.status_code}"}, indent=4)
                
                # Upload the poster
                playlist.uploadPoster(url=poster_url)
                return json.dumps({
                    "updated": True,
                    "poster_source": "url",
                    "title": playlist.title
                }, indent=4)
            except Exception as url_error:
                return json.dumps({"error": f"Error uploading from URL: {str(url_error)}"}, indent=4)
        
        # Upload from file
        if poster_filepath:
            if not os.path.exists(poster_filepath):
                return json.dumps({"error": f"File not found: {poster_filepath}"}, indent=4)
            
            try:
                # Upload the poster
                playlist.uploadPoster(filepath=poster_filepath)
                return json.dumps({
                    "updated": True,
                    "poster_source": "file",
                    "title": playlist.title
                }, indent=4)
            except Exception as file_error:
                return json.dumps({"error": f"Error uploading from file: {str(file_error)}"}, indent=4)
        
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def playlist_copy_to_user(playlist_title: str = None, playlist_id: int = None, username: str = None) -> str:
    """Copy a playlist to another user account.
    
    Args:
        playlist_title: Title of the playlist to copy (optional if playlist_id is provided)
        playlist_id: ID of the playlist to copy (optional if playlist_title is provided)
        username: Username of the user to copy the playlist to
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"status": "error", "message": "Either playlist_id or playlist_title must be provided"}, indent=4)
        
        if not username:
            return json.dumps({"status": "error", "message": "Username must be provided"}, indent=4)
        
        # Find the playlist
        playlist = None
        
        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)
                
                if playlist is None:
                    return json.dumps({"status": "error", "message": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"status": "error", "message": f"Error fetching playlist by ID: {str(e)}"}, indent=4)
        else:
            # Search by title
            playlists = plex.playlists()
            matching_playlists = [p for p in playlists if p.title.lower() == playlist_title.lower()]
            
            if not matching_playlists:
                return json.dumps({"status": "error", "message": f"No playlist found with title '{playlist_title}'"}, indent=4)
            
            # If multiple matching playlists, return list of matches with IDs
            if len(matching_playlists) > 1:
                matches = []
                for p in matching_playlists:
                    matches.append({
                        "title": p.title,
                        "id": p.ratingKey,
                        "type": p.playlistType,
                        "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                    })
                
                return json.dumps({
                    "status": "multiple_matches",
                    "message": f"Found {len(matching_playlists)} playlists with title '{playlist_title}'. Please specify the playlist ID.",
                    "matches": matches
                }, indent=4)
                
            playlist = matching_playlists[0]
        
        # Find the user
        users = plex.myPlexAccount().users()
        user = next((u for u in users if u.title.lower() == username.lower()), None)
        
        if not user:
            return json.dumps({"status": "error", "message": f"User '{username}' not found"}, indent=4)
        
        # Copy the playlist
        playlist.copyToUser(user=user)
        
        return json.dumps({
            "status": "success", 
            "message": f"Playlist '{playlist.title}' copied to user '{username}'"
        }, indent=4)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=4)

@mcp.tool()
async def playlist_add_to(playlist_title: str = None, playlist_id: int = None, item_titles: List[str] = None, item_ids: List[int] = None) -> str:
    """Add items to a playlist.
    
    Args:
        playlist_title: Title of the playlist to add to (optional if playlist_id is provided)
        playlist_id: ID of the playlist to add to (optional if playlist_title is provided)
        item_titles: List of media titles to add to the playlist (optional if item_ids is provided)
        item_ids: List of media IDs to add to the playlist (optional if item_titles is provided)
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)
        
        # Validate that at least one item source is provided
        if (not item_titles or len(item_titles) == 0) and (not item_ids or len(item_ids) == 0):
            return json.dumps({"error": "Either item_titles or item_ids must be provided"}, indent=4)
        
        # Find the playlist
        playlist = None
        
        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)
                
                if playlist is None:
                    return json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)
        else:
            # Search by title
            playlists = plex.playlists()
            matching_playlists = [p for p in playlists if p.title.lower() == playlist_title.lower()]
            
            if not matching_playlists:
                return json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)
            
            # If multiple matching playlists, return list of matches with IDs
            if len(matching_playlists) > 1:
                matches = []
                for p in matching_playlists:
                    matches.append({
                        "title": p.title,
                        "id": p.ratingKey,
                        "type": p.playlistType,
                        "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps({"Multiple Matches":matches}, indent=4)
                
            playlist = matching_playlists[0]
        
        # Find items to add
        items_to_add = []
        not_found = []
        
        # If we have item IDs, try to add by ID first
        if item_ids and len(item_ids) > 0:
            for item_id in item_ids:
                try:
                    # Try to fetch the item by ID
                    item = plex.fetchItem(item_id)
                    if item:
                        items_to_add.append(item)
                    else:
                        not_found.append(str(item_id))
                except Exception as e:
                    not_found.append(str(item_id))
        
        # If we have item titles, search for them
        if item_titles and len(item_titles) > 0:
            # Search all library sections
            all_sections = plex.library.sections()
            
            for title in item_titles:
                found_item = None
                possible_matches = []
                
                # Try to find the item in each section
                for section in all_sections:
                    # Skip photo libraries
                    if section.type in ['photo']:
                        continue
                    
                    search_results = section.search(title)
                    if search_results:
                        # Check for exact title match (case insensitive)
                        exact_matches = [item for item in search_results if item.title.lower() == title.lower()]
                        if exact_matches:
                            found_item = exact_matches[0]
                            break
                        else:
                            # Add to possible matches if not an exact match
                            for item in search_results:
                                possible_matches.append({
                                    "title": item.title,
                                    "id": item.ratingKey,
                                    "type": item.type,
                                    "year": item.year if hasattr(item, 'year') and item.year else None
                                })
                
                if found_item:
                    items_to_add.append(found_item)
                elif possible_matches:
                    # If we have possible matches but no exact match, add title to not_found
                    # and store the possible matches to return later
                    not_found.append({
                        "title": title,
                        "possible_matches": possible_matches
                    })
                else:
                    not_found.append(title)
        
        if not items_to_add:
            # If we have possible matches, return them
            if any(isinstance(item, dict) for item in not_found):
                possible_matches_response = []
                for item in not_found:
                    if isinstance(item, dict) and "possible_matches" in item:
                        for match in item["possible_matches"]:
                            if match not in possible_matches_response:
                                possible_matches_response.append(match)
                    
                return json.dumps({"Multiple Possible Matches Use ID" : possible_matches_response}, indent=4)
            
            return json.dumps({"error": "No matching items found to add to the playlist"}, indent=4)
        
        # Add items to the playlist
        for item in items_to_add:
            playlist.addItems(item)
        
        return json.dumps({
            "added": True,
            "title": playlist.title,
            "items_added": [item.title for item in items_to_add],
            "items_not_found": not_found,
            "total_items": len(playlist.items())
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def playlist_remove_from(playlist_title: str = None, playlist_id: int = None, item_titles: List[str] = None) -> str:
    """Remove items from a playlist.
    
    Args:
        playlist_title: Title of the playlist to remove from (optional if playlist_id is provided)
        playlist_id: ID of the playlist to remove from (optional if playlist_title is provided)
        item_titles: List of media titles to remove from the playlist
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)
        
        if not item_titles or len(item_titles) == 0:
            return json.dumps({"error": "At least one item title must be provided to remove"}, indent=4)
        
        # Find the playlist
        playlist = None
        
        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)
                
                if playlist is None:
                    return json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)
        else:
            # Search by title
            playlists = plex.playlists()
            matching_playlists = [p for p in playlists if p.title.lower() == playlist_title.lower()]
            
            if not matching_playlists:
                return json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)
            
            # If multiple matching playlists, return list of matches with IDs
            if len(matching_playlists) > 1:
                matches = []
                for p in matching_playlists:
                    matches.append({
                        "title": p.title,
                        "id": p.ratingKey,
                        "type": p.playlistType,
                        "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps({"Multiple Matches":matches}, indent=4)
                
            playlist = matching_playlists[0]
        
        # Get current items in the playlist
        playlist_items = playlist.items()
        
        # Find items to remove
        items_to_remove = []
        not_found = []
        
        for title in item_titles:
            found = False
            for item in playlist_items:
                if item.title.lower() == title.lower():
                    items_to_remove.append(item)
                    found = True
                    break
            if not found:
                not_found.append(title)
        
        if not items_to_remove:
            # No items found to remove, return the current playlist contents
            current_items = []
            for item in playlist_items:
                current_items.append({
                    "title": item.title,
                    "type": item.type,
                    "id": item.ratingKey
                })
            
            return json.dumps({
                "error": "No matching items found in the playlist to remove",
                "playlist_title": playlist.title,
                "playlist_id": playlist.ratingKey,
                "current_items": current_items
            }, indent=4)
        
        # Remove items from the playlist
        # Using removeItems (plural) since removeItem is deprecated
        playlist.removeItems(items_to_remove)
        
        return json.dumps({
            "removed": True,
            "title": playlist.title,
            "items_removed": [item.title for item in items_to_remove],
            "items_not_found": not_found,
            "remaining_items": len(playlist.items())
        }, indent=4)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool()
async def playlist_delete(playlist_title: str = None, playlist_id: int = None) -> str:
    """Delete a playlist.
    
    Args:
        playlist_title: Title of the playlist to delete (optional if playlist_id is provided)
        playlist_id: ID of the playlist to delete (optional if playlist_title is provided)
    """
    try:
        plex = connect_to_plex()
        
        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)
        
        # Find the playlist
        playlist = None
        
        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)
                
                if playlist is None:
                    return json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
            except Exception as e:
                return json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)
        else:
            # Search by title
            playlists = plex.playlists()
            matching_playlists = [p for p in playlists if p.title.lower() == playlist_title.lower()]
            
            if not matching_playlists:
                return json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)
            
            # If multiple matching playlists, return list of matches with IDs
            if len(matching_playlists) > 1:
                matches = []
                for p in matching_playlists:
                    matches.append({
                        "title": p.title,
                        "id": p.ratingKey,
                        "type": p.playlistType,
                        "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                    })
                
                # Return as a direct array like playlist_list
                return json.dumps(matches, indent=4)
                
            playlist = matching_playlists[0]
        
        # Get the playlist title to return in the message
        playlist_title_to_return = playlist.title
        
        # Delete the playlist
        playlist.delete()
        
        # Return a simple object with the result
        return json.dumps({
            "deleted": True,
            "title": playlist_title_to_return
        }, indent=4)
        
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=4)

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def playlist_get_contents(playlist_title: str = None, playlist_id: int = None,
                                limit: int = None, offset: int = 0, include_items: bool = True) -> str:
    """Get the contents of a playlist, with pagination.

    Results are paginated so large playlists don't overflow the response. The response includes
    `totalItems`, `offset`, `limit`, `returnedCount`, and `hasMore`; page through by increasing
    `offset`. For a smart playlist the response also includes `smartFilter` (the saved search that
    populates it, in the form the create/edit tools accept) and `smartFilterRaw` (the same filter
    as Plex stores it on the wire). Compare the two when verifying what a write actually saved:
    the wire form spells operators differently, so `title=` in `smartFilter` is `title==` in
    `smartFilterRaw` and both mean an exact match. If the filter can't be read, `smartFilter`
    carries an `error` explaining why rather than going missing.

    Args:
        playlist_title: Title of the playlist to get contents of (optional if playlist_id is provided)
        playlist_id: ID of the playlist to get contents of (optional if playlist_title is provided)
        limit: Maximum number of items to return in this page (defaults to 200)
        offset: Number of items to skip before this page (for paging; default 0)
        include_items: When False, skip the item list entirely and return only metadata and, for a
            smart playlist, its `smartFilter`. Use this to read a huge smart playlist's filter cheaply.

    Returns:
        JSON object containing the playlist metadata and (unless include_items is False) one page of items
    """
    try:
        plex = connect_to_plex()

        # Validate that at least one identifier is provided
        if not playlist_id and not playlist_title:
            return json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)

        # If playlist_id is provided, use it to directly fetch the playlist
        if playlist_id:
            try:
                playlist = None
                # Try fetching by ratingKey first
                try:
                    playlist = plex.fetchItem(playlist_id)
                except:
                    # If that fails, try finding by key in all playlists
                    all_playlists = plex.playlists()
                    playlist = next((p for p in all_playlists if p.ratingKey == playlist_id), None)

                if playlist is None:
                    return json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)

                # Get playlist contents
                return get_playlist_contents(playlist, offset=offset, limit=limit, include_items=include_items)
            except Exception as e:
                if "500" in str(e):
                    return json.dumps({"error": "Empty playlist"}, indent=4)
                else:
                    return json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)

        # If we get here, we're searching by title
        all_playlists = plex.playlists()
        matching_playlists = [p for p in all_playlists if p.title.lower() == playlist_title.lower()]

        # If no matching playlists
        if not matching_playlists:
            return json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)

        # If multiple matching playlists, return list of matches with IDs
        if len(matching_playlists) > 1:
            matches = []
            for p in matching_playlists:
                matches.append({
                    "title": p.title,
                    "id": p.ratingKey,
                    "type": p.playlistType,
                    "item_count": p.leafCount if hasattr(p, 'leafCount') else len(p.items())
                })

            # Return as a direct array like playlist_list
            return json.dumps(matches, indent=4)

        # Single match - get contents
        return get_playlist_contents(matching_playlists[0], offset=offset, limit=limit, include_items=include_items)

    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error getting playlist contents: {str(e)}"}, indent=4)

def get_playlist_contents(playlist, offset=0, limit=None, include_items=True):
    """Helper function to get formatted, paginated playlist contents.

    Pagination is done server-side (Plex container params), so only the requested page is fetched.
    When include_items is False, no items are fetched at all - only metadata and the smart filter.
    """
    try:
        # Capture the filter URI before reloading: a playlist's key addresses its
        # /items representation, which need not carry 'content'.
        raw_content = getattr(playlist, 'content', None)

        # Refresh so totalItems (leafCount) is current
        try:
            playlist.reload()
        except Exception:
            pass
        total = getattr(playlist, 'leafCount', None)

        is_smart = bool(getattr(playlist, 'smart', False))

        playlist_info = {
            "title": playlist.title,
            "id": playlist.ratingKey,
            "key": playlist.key,
            "type": playlist.playlistType,
            "smart": is_smart,
            "summary": playlist.summary if hasattr(playlist, 'summary') else None,
            "duration": playlist.duration if hasattr(playlist, 'duration') else None,
            "totalItems": total
        }
        # Include the smart filter definition so it can be read back before editing
        if is_smart:
            playlist_info.update(describe_smart_filter(playlist, raw_content))

        # Filter-only mode: skip fetching items entirely
        if not include_items:
            playlist_info["itemsIncluded"] = False
            return json.dumps(playlist_info, indent=4)

        # Fetch just the requested page of items (server-side pagination)
        page_size = limit if limit is not None else DEFAULT_CONTENTS_PAGE
        offset = max(0, offset or 0)
        items = playlist.fetchItems(f'{playlist.key}/items', container_start=offset, container_size=page_size)

        playlist_items = []
        for i, item in enumerate(items):
            position = offset + i + 1
            item_data = {
                "title": item.title,
                "type": item.type,
                "position": position,
                "playlistItemID": item.playlistItemID if hasattr(item, 'playlistItemID') else None,
                "ratingKey": item.ratingKey,
                "addedAt": item.addedAt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(item, 'addedAt') and item.addedAt else None,
                "duration": item.duration if hasattr(item, 'duration') else None,
                "thumb": item.thumb if hasattr(item, 'thumb') else None
            }

            # Add media-type specific fields
            if item.type == 'movie':
                item_data["year"] = item.year if hasattr(item, 'year') else None
            elif item.type == 'episode':
                item_data["show"] = item.grandparentTitle if hasattr(item, 'grandparentTitle') else None
                item_data["season"] = item.parentTitle if hasattr(item, 'parentTitle') else None
                item_data["seasonNumber"] = item.parentIndex if hasattr(item, 'parentIndex') else None
                item_data["episodeNumber"] = item.index if hasattr(item, 'index') else None
            elif item.type == 'track':
                item_data["artist"] = item.grandparentTitle if hasattr(item, 'grandparentTitle') else None
                item_data["album"] = item.parentTitle if hasattr(item, 'parentTitle') else None
                item_data["albumArtist"] = item.originalTitle if hasattr(item, 'originalTitle') else None

            playlist_items.append(item_data)

        returned = len(playlist_items)
        if total is not None:
            has_more = offset + returned < total
        else:
            has_more = returned == page_size

        playlist_info.update({
            "offset": offset,
            "limit": page_size,
            "returnedCount": returned,
            "hasMore": has_more,
            "items": playlist_items
        })
        
        # Return just the playlist info without status wrappers
        return json.dumps(playlist_info, indent=4)
    except Exception as e:
        return json.dumps({"error": f"Error formatting playlist contents: {str(e)}"}, indent=4)


@mcp.tool()
async def playlist_move_item(playlist_title: str = None, playlist_id: int = None,
                             item_playlist_item_id: int = None, new_position: int = None) -> str:
    """Move a single item to a new position within a regular playlist.

    Reordering is keyed off playlistItemID (unique per row, so it handles a
    playlist that contains the same item more than once). Call
    playlist_get_contents first to read each row's playlistItemID and current
    1-based position, then pass the row's playlistItemID and the target
    new_position here.

    Note: smart playlists cannot be reordered manually; their order is driven
    by the saved filter/sort.

    Args:
        playlist_title: Title of the playlist (optional if playlist_id is provided)
        playlist_id: ID of the playlist (optional if playlist_title is provided)
        item_playlist_item_id: playlistItemID of the row to move (from playlist_get_contents)
        new_position: Target 1-based position for the item

    Returns:
        JSON object with the reordered playlist contents, or an error
    """
    try:
        plex = connect_to_plex()

        playlist, error_response = _resolve_playlist(plex, playlist_title, playlist_id)
        if error_response is not None:
            return error_response

        if getattr(playlist, 'smart', False):
            return json.dumps({"error": "Smart playlists cannot be reordered manually; their order is driven by the saved filter."}, indent=4)

        if item_playlist_item_id is None:
            return json.dumps({"error": "item_playlist_item_id must be provided (see playlist_get_contents)"}, indent=4)
        if new_position is None:
            return json.dumps({"error": "new_position must be provided (1-based)"}, indent=4)

        items = playlist.items()
        target = next((i for i in items if getattr(i, 'playlistItemID', None) == item_playlist_item_id), None)
        if target is None:
            return json.dumps({"error": f"No item with playlistItemID '{item_playlist_item_id}' found in this playlist"}, indent=4)

        if new_position < 1 or new_position > len(items):
            return json.dumps({"error": f"new_position must be between 1 and {len(items)}"}, indent=4)

        # Build the list without the moved row so the target slot maps to an
        # "after" anchor. moveItem places target immediately after `after`
        # (after=None moves it to the top).
        others = [i for i in items if getattr(i, 'playlistItemID', None) != item_playlist_item_id]
        idx = new_position - 1
        after = None if idx <= 0 else others[idx - 1]

        playlist.moveItem(target, after=after)
        playlist.reload()

        return get_playlist_contents(playlist)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error moving playlist item: {str(e)}"}, indent=4)


def _resolve_playlist(plex, playlist_title: str = None, playlist_id: int = None):
    """Resolve a playlist by id or title.

    Returns a tuple (playlist, error_response). On success, playlist is the
    matched Playlist and error_response is None. On failure or ambiguity,
    playlist is None and error_response is a JSON string ready to return.
    """
    if not playlist_id and not playlist_title:
        return None, json.dumps({"error": "Either playlist_id or playlist_title must be provided"}, indent=4)

    # Fetch directly by id when provided
    if playlist_id:
        try:
            try:
                playlist = plex.fetchItem(playlist_id)
            except Exception:
                # Fall back to matching by ratingKey across all playlists
                playlist = next((p for p in plex.playlists() if p.ratingKey == playlist_id), None)
            if playlist is None:
                return None, json.dumps({"error": f"Playlist with ID '{playlist_id}' not found"}, indent=4)
            return playlist, None
        except Exception as e:
            return None, json.dumps({"error": f"Error fetching playlist by ID: {str(e)}"}, indent=4)

    # Otherwise match by title
    matching = [p for p in plex.playlists() if p.title.lower() == playlist_title.lower()]
    if not matching:
        return None, json.dumps({"error": f"No playlist found with title '{playlist_title}'"}, indent=4)
    if len(matching) > 1:
        # Ambiguous title: return the candidates so the caller can pick an id
        matches = [{
            "title": p.title,
            "id": p.ratingKey,
            "type": p.playlistType
        } for p in matching]
        return None, json.dumps(matches, indent=4)
    return matching[0], None


@mcp.tool()
async def playlist_create_smart(playlist_title: str, library_name: str, filters: dict = None,
                                sort: str = None, limit: int = None, libtype: str = None,
                                summary: str = None) -> str:
    """Create a smart playlist that Plex keeps auto-populated from a library search.

    Unlike playlist_create (a fixed list of items), a smart playlist is a saved filter
    scoped to a single library section. Use library_get_smart_filter_options first to
    discover the available filter fields, operators, sort fields, and valid values.

    Args:
        playlist_title: Title for the new smart playlist
        library_name: Library section the playlist is built from (smart playlists are single-section)
        filters: Advanced filters as a dict, e.g. {"genre": "Comedy", "year>>": 2000, "unwatched": true}.
            Append an operator suffix (see library_get_smart_filter_options) to a field for
            comparisons. No suffix on a string field means 'contains', not exact match:
            "title" matches substrings, "title=" is exact.
        sort: Sort field(s), e.g. "addedAt:desc" or "year:asc". Comma-separate multiple fields.
        limit: Maximum number of items in the playlist
        libtype: Content type to filter (movie, show, season, episode, artist, album, track, photo).
            Defaults to the section's type - note this is 'episode' for TV libraries and 'track' for
            music, so set libtype='show'/'artist' if you want whole shows/artists.
        summary: Optional description for the playlist
    """
    try:
        plex = connect_to_plex()
        try:
            section = plex.library.section(library_name)
        except NotFound:
            return json.dumps({"error": f"Library '{library_name}' not found"}, indent=4)

        try:
            playlist = plex.createPlaylist(
                title=playlist_title,
                section=section,
                smart=True,
                filters=filters,
                sort=sort,
                limit=limit,
                libtype=libtype
            )
        except BadRequest as e:
            return json.dumps({"status": "error", "message": f"Invalid smart playlist definition: {str(e)}"}, indent=4)

        # Apply an optional summary after creation
        if summary:
            try:
                playlist.editSummary(summary)
            except Exception:
                pass

        # Reload so item_count reflects what the filter actually matched, not a
        # stale value from creation - verify this count looks right for the filter.
        try:
            playlist.reload()
        except Exception:
            pass

        return json.dumps({
            "status": "success",
            "message": f"Smart playlist '{playlist_title}' created successfully",
            "data": {
                "title": playlist.title,
                "key": playlist.key,
                "ratingKey": playlist.ratingKey,
                "smart": True,
                "library": section.title,
                "item_count": playlist.leafCount if hasattr(playlist, 'leafCount') else None
            }
        }, indent=4)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=4)


@mcp.tool()
async def playlist_edit_smart_filters(playlist_title: str = None, playlist_id: int = None,
                                      filters: dict = None, sort: str = None, limit: int = None) -> str:
    """Update the filter definition of an existing smart playlist.

    This replaces the smart playlist's search criteria; Plex re-evaluates it immediately.
    Only works on smart playlists - use playlist_edit for a regular playlist's title/summary.

    Args:
        playlist_title: Title of the smart playlist to edit (optional if playlist_id is provided)
        playlist_id: ID of the smart playlist to edit (optional if playlist_title is provided)
        filters: New advanced filters as a dict, e.g. {"genre": "Drama", "year>>": 2010}.
            See library_get_smart_filter_options for available fields, operators, and values.
            No suffix on a string field means 'contains': "title=" is the exact match.
        sort: New sort field(s), e.g. "addedAt:desc"
        limit: New maximum number of items in the playlist
    """
    try:
        plex = connect_to_plex()

        playlist, error_response = _resolve_playlist(plex, playlist_title, playlist_id)
        if error_response is not None:
            return error_response

        if not getattr(playlist, 'smart', False):
            return json.dumps({
                "status": "error",
                "message": f"Playlist '{playlist.title}' is not a smart playlist; its filters cannot be edited"
            }, indent=4)

        try:
            playlist.updateFilters(limit=limit, sort=sort, filters=filters)
        except BadRequest as e:
            return json.dumps({"status": "error", "message": f"Invalid smart playlist filters: {str(e)}"}, indent=4)

        playlist.reload()
        return json.dumps({
            "status": "success",
            "message": f"Smart playlist '{playlist.title}' filters updated successfully",
            "data": {
                "title": playlist.title,
                "ratingKey": playlist.ratingKey,
                "item_count": playlist.leafCount if hasattr(playlist, 'leafCount') else None
            }
        }, indent=4)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=4)
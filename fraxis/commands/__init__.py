# Copyright (c) 2026, Picurit and contributors
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
# For license information, please see license.txt

def get_commands():
	# make sure to prevent circular imports
	from .socketio_server import SocketIOManager

	clickable_link = "https://github.com/picurit/fraxis"
	all_commands = (
        *SocketIOManager.get_commands(),
	)

	for command in all_commands:
		if not command.help:
			command.help = f"Refer to {clickable_link}"

	return all_commands

commands = get_commands()

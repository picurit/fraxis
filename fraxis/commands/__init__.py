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

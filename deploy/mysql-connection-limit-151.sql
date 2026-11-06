-- Run once with a MySQL administrator account.
-- Target: the application instance on port 23306, not the instance on 3306.
-- Updates the running global limit and persists it across restarts.
SET PERSIST max_connections = 151;
ALTER USER 'zdhgj'@'%' WITH MAX_USER_CONNECTIONS 151;

SELECT @@GLOBAL.max_connections AS max_connections;
SELECT User, Host, max_user_connections
FROM mysql.user
WHERE User = 'zdhgj' AND Host = '%';
SELECT VARIABLE_NAME, VARIABLE_VALUE
FROM performance_schema.persisted_variables
WHERE VARIABLE_NAME = 'max_connections';

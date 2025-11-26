CREATE USER 'admin1'@'localhost' IDENTIFIED BY 'pass_test1';

CREATE DATABASE poc_paywall;

GRANT ALL PRIVILEGES ON poc_paywall.* TO 'admin1'@'localhost';
FLUSH PRIVILEGES;
"""Private, persistent authentication for the dedicated development database."""
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from contextlib import contextmanager


@contextmanager
def private_directory(path):
    """Pin the private directory; never follow its final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('Neo4j bootstrap refused')
        yield fd
    finally:
        os.close(fd)


def _read_auth(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError('Neo4j bootstrap refused')
        auth = os.read(fd, 64).decode('ascii')
        if not re.fullmatch(r'neo4j/[A-Za-z0-9_-]{43}', auth):
            raise RuntimeError('Neo4j bootstrap refused')
        return auth
    finally:
        os.close(fd)


def read_auth(path):
    """Read a validated secret; callers must never log its value."""
    try:
        path = Path(path)
        with private_directory(path.parent) as directory:
            return _read_auth(directory, path.name)
    except (OSError, UnicodeError):
        raise RuntimeError('Neo4j bootstrap refused') from None


def fresh_data(data):
    """Only empty data or the pinned image's empty directory skeleton is fresh."""
    directory = os.open(data, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(directory).st_uid != os.geteuid():
            return False
        for name in os.listdir(directory):
            if name not in {'databases', 'transactions'}:
                return False
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except OSError:
                return False
            try:
                if os.listdir(child):
                    return False
            finally:
                os.close(child)
        return True
    finally:
        os.close(directory)


def ensure_auth(path, data):
    """Create once, mode 0600 from the first open; never repair/replace."""
    try:
        path = Path(path)
        with private_directory(path.parent) as directory:
            try:
                os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                if not fresh_data(data):
                    raise RuntimeError('Neo4j bootstrap refused')
                try:
                    fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, 'w', encoding='ascii') as stream:
                        stream.write('neo4j/' + secrets.token_urlsafe(32))
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.fsync(directory)
            return _read_auth(directory, path.name)
    except (OSError, UnicodeError):
        raise RuntimeError('Neo4j bootstrap refused') from None


def validate_environment(env):
    """Reject upstream secret, config-location and execution escape hatches."""
    forbidden = {'EXTENSION_SCRIPT', 'EXTENDED_CONF', 'JAVA_TOOL_OPTIONS',
                 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'NEO4J_CONF',
                 'NEO4J_PLUGINS', 'NEO4JLABS_PLUGINS', 'NEO4J_DEBUG'}
    for key, value in env.items():
        if key == 'NEO4J_dbms_security_auth__enabled' and value == 'true':
            continue
        if key == 'NEO4J_HOME' and value == '/var/lib/neo4j':
            continue
        if (key in forbidden or key == 'NEO4J_HOME' or key.startswith('NEO4J_AUTH')
                or (key.startswith('NEO4J_') and ('auth' in key.lower()
                    or key.endswith('_FILE') or key.startswith('NEO4J_server_directories_')))):
            raise RuntimeError('Neo4j bootstrap refused')


def initialize_password(auth, data):
    """Use Neo4j's own password command in-process, with only stdin secret input.

    The pinned CLI has no --from-stdin; NEO4J_AUTH_PATH still puts the password
    in a child argv. A fixed compiled Java bridge avoids both that exposure and
    implementing Neo4j's hash/storage format ourselves.
    """
    data = Path(data)
    if not fresh_data(data):
        if any(not (data / name).is_symlink() and (data / name).is_dir()
               and any((data / name).iterdir())
               for name in ('databases', 'transactions')):
            return
        # A crash during the Java bridge must not lead to a default-password
        # startup. Only a completed, private upstream auth.ini permits resuming.
        try:
            with private_directory(data / 'dbms') as directory:
                info = os.stat('auth.ini', dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
                        or info.st_size == 0):
                    raise RuntimeError('Neo4j bootstrap refused')
        except OSError:
            raise RuntimeError('Neo4j bootstrap refused') from None
        return
    subprocess.run(
        ['java', '-cp', '/var/lib/neo4j/lib/*:/opt/automator-neo4j',
         'AutomatorInitialPassword'],
        input=auth.split('/', 1)[1].encode('ascii'),
        env={'PATH': '/opt/java/openjdk/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'},
        cwd='/var/lib/neo4j', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=True, timeout=60,
    )


# Compiled at image build time against the pinned distribution, never supplied
# by the caller. No password is present at build time and no child gets it in argv.
JAVA_HELPER = r'''
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import org.neo4j.cli.ExecutionContext;
import org.neo4j.commandline.admin.security.SetInitialPasswordCommand;
import picocli.CommandLine;

public final class AutomatorInitialPassword {
    public static void main(String[] args) {
        try {
            if (args.length != 0) System.exit(1);
            byte[] input = System.in.readNBytes(44);
            String password = new String(input, StandardCharsets.US_ASCII);
            if (!password.matches("[A-Za-z0-9_-]{43}")) System.exit(1);
            var context = new ExecutionContext(
                Path.of("/var/lib/neo4j"), Path.of("/var/lib/neo4j/conf"));
            int result = new CommandLine(new SetInitialPasswordCommand(context)).execute("--", password);
            java.util.Arrays.fill(input, (byte) 0);
            System.exit(result);
        } catch (Throwable failure) {
            System.exit(1);
        }
    }
}
'''


def build_helper(destination):
    """Image-build-only compilation of the fixed bridge; no runtime CLI mode."""
    source = Path(destination) / 'AutomatorInitialPassword.java'
    source.write_text(JAVA_HELPER, encoding='utf-8')
    try:
        subprocess.run(['javac', '-cp', '/var/lib/neo4j/lib/*', str(source)], check=True)
    finally:
        source.unlink()


def main(argv=None):
    try:
        if (sys.argv[1:] if argv is None else argv) or os.geteuid() != 7474:
            raise RuntimeError('Neo4j bootstrap refused')
        validate_environment(os.environ)
        os.umask(0o077)
        auth = ensure_auth('/automator-secrets/auth', '/data')
        initialize_password(auth, '/data')
        del auth
        env = dict(os.environ)
        env['NEO4J_dbms_security_auth__enabled'] = 'true'
        os.execve('/startup/docker-entrypoint.sh',
                  ['/startup/docker-entrypoint.sh', 'neo4j'], env)
        return 0
    except Exception:
        print('Neo4j bootstrap refused', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

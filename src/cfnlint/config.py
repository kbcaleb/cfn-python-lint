"""
  Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.

  Permission is hereby granted, free of charge, to any person obtaining a copy of this
  software and associated documentation files (the "Software"), to deal in the Software
  without restriction, including without limitation the rights to use, copy, modify,
  merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
  permit persons to whom the Software is furnished to do so.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
  INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
  PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
  HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
  OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
  SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
import sys
import argparse
import logging
import glob
import json
import os
import copy
import six
import jsonschema
import cfnlint.decode.cfn_yaml
from cfnlint.version import __version__
try:  # pragma: no cover
    from pathlib import Path
except ImportError:  # pragma: no cover
    from pathlib2 import Path

LOGGER = logging.getLogger('cfnlint')


def configure_logging(debug_logging, info_logging):
    """Setup Logging"""
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    if debug_logging:
        LOGGER.setLevel(logging.DEBUG)
    elif info_logging:
        LOGGER.setLevel(logging.INFO)
    else:
        LOGGER.setLevel(logging.NOTSET)
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(log_formatter)

    # make sure all other log handlers are removed before adding it back
    for handler in LOGGER.handlers:
        LOGGER.removeHandler(handler)
    LOGGER.addHandler(ch)


class ConfigFileArgs(object):
    """
        Config File arguments.
        Parses .cfnlintrc in the Home and Project folder.
    """
    file_args = {}

    def __init__(self, schema=None):
        # self.file_args = self.get_config_file_defaults()
        self.__user_config_file = None
        self.__project_config_file = None
        self.file_args = {}
        self.default_schema_file = Path(__file__).parent.joinpath('data/CfnLintCli/config/schema.json')
        with self.default_schema_file.open() as f:
            self.default_schema = json.load(f)
        self.schema = self.default_schema if not schema else schema
        self.load()

    def _find_config(self):
        """Looks up for user and project level config
        Returns
        -------
        Tuple
            (Path, Path)
            Tuple with both configs and whether they were found
        Example
        -------
            > user_config, project_config = self._find_config()
        """
        config_file_name = '.cfnlintrc'
        if six.PY34:
            self.__user_config_file = Path(os.path.expanduser('~')).joinpath(config_file_name)
        else:
            self.__user_config_file = Path.home().joinpath(config_file_name)
        self.__project_config_file = Path.cwd().joinpath(config_file_name)

        user_config_path = ''
        project_config_path = ''

        if self._has_file(self.__user_config_file):
            LOGGER.debug('Found User CFNLINTRC')
            user_config_path = self.__user_config_file

        if self._has_file(self.__project_config_file):
            LOGGER.debug('Found Project level CFNLINTRC')
            project_config_path = self.__project_config_file

        return user_config_path, project_config_path

    def _has_file(self, filename):
        """Confirm whether file exists
        Parameters
        ----------
        filename : str
            Path to a file
        Returns
        -------
        Boolean
        """

        return Path(filename).is_file()

    def load(self):
        """Load configuration file and expose as a dictionary
        Returns
        -------
        Dict
            CFLINTRC configuration
        """

        LOGGER.debug('Looking for CFLINTRC before attempting to load')
        user_config, project_config = self._find_config()

        user_config = self._read_config(user_config)
        LOGGER.debug('Validating User CFNLINTRC')
        self.validate_config(user_config, self.schema)

        project_config = self._read_config(project_config)
        LOGGER.debug('Validating Project CFNLINTRC')
        self.validate_config(project_config, self.schema)

        LOGGER.debug('User configuration loaded as')
        LOGGER.debug('%s', user_config)
        LOGGER.debug('Project configuration loaded as')
        LOGGER.debug('%s', project_config)

        LOGGER.debug('Merging configurations...')
        self.file_args = self.merge_config(user_config, project_config)

    def validate_config(self, config, schema):
        """Validate configuration against schema
        Parameters
        ----------
        config : dict
            CFNLINTRC configuration
        schema : dict
            JSONSchema to validate against
        Raises
        -------
        jsonschema.exceptions.ValidationError
            Returned when cfnlintrc doesn't match schema provided
        """
        LOGGER.debug('Validating CFNLINTRC config with given JSONSchema')
        LOGGER.debug('Schema used: %s', schema)
        LOGGER.debug('Config used: %s', config)

        jsonschema.validate(config, schema)
        LOGGER.debug('CFNLINTRC looks valid!')

    def merge_config(self, user_config, project_config):
        """Merge project and user configuration into a single dictionary
        Creates a new configuration with both configuration merged
        it favours project level over user configuration if keys are duplicated
        NOTE
        ----
            It takes any number of nested dicts
            It overrides lists found in user_config with project_config
        Parameters
        ----------
        user_config : Dict
            User configuration (~/.cfnlintrc) found at user's home directory
        project_config : Dict
            Project configuration (.cfnlintrc) found at current directory
        Returns
        -------
        Dict
            Merged configuration
        """
        # Recursively override User config with Project config
        for key in user_config:
            if key in project_config:
                # If both keys are the same, let's check whether they have nested keys
                if isinstance(user_config[key], dict) and isinstance(project_config[key], dict):
                    self.merge_config(user_config[key], project_config[key])
                else:
                    user_config[key] = project_config[key]
                    LOGGER.debug('Overriding User\'s key %s with Project\'s specific value %s.', key, project_config[key])

        # Project may have unique config we need to copy over too
        # so that we can have user+project config available as one
        for key in project_config:
            if key not in user_config:
                user_config[key] = project_config[key]

        return user_config

    def _read_config(self, config):
        """Parse given YAML configuration
        Returns
        -------
        Dict
            Parsed YAML configuration as dictionary
        """
        config = Path(config)
        config_template = None

        if self._has_file(config):
            LOGGER.debug('Parsing CFNLINTRC')
            config_template = cfnlint.decode.cfn_yaml.load(str(config))

        if not config_template:
            config_template = {}

        return config_template


def comma_separated_arg(string):
    """ Split a comma separated string """
    return string.split(',')


def _ensure_value(namespace, name, value):
    if getattr(namespace, name, None) is None:
        setattr(namespace, name, value)
    return getattr(namespace, name)


class RuleConfigurationAction(argparse.Action):
    """ Override the default Action """
    def __init__(self, option_strings, dest, nargs=None, const=None, default=None,
                 type=None, choices=None, required=False, help=None, metavar=None):  # pylint: disable=W0622
        super(RuleConfigurationAction, self).__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=nargs,
            const=const,
            default=default,
            type=type,
            choices=choices,
            required=required,
            help=help,
            metavar=metavar)

    def _parse_rule_configuration(self, string):
        """ Parse the config rule structure """
        configs = comma_separated_arg(string)
        results = {}
        for config in configs:
            rule_id = config.split(':')[0]
            config_name = config.split(':')[1].split('=')[0]
            config_value = config.split(':')[1].split('=')[1]
            if rule_id not in results:
                results[rule_id] = {}
            results[rule_id][config_name] = config_value

        return results

    def __call__(self, parser, namespace, values, option_string=None):
        items = copy.copy(_ensure_value(namespace, self.dest, {}))
        try:
            for value in values:
                new_value = self._parse_rule_configuration(value)
                for v_k, v_vs in new_value.items():
                    if v_k in items:
                        for s_k, s_v in v_vs.items():
                            items[v_k][s_k] = s_v
                    else:
                        items[v_k] = v_vs
            setattr(namespace, self.dest, items)
        except Exception:  # pylint: disable=W0703
            parser.print_help()
            parser.exit()


class CliArgs(object):
    """ Base Args class"""
    cli_args = {}

    def __init__(self, cli_args):
        self.parser = self.create_parser()
        self.cli_args, _ = self.parser.parse_known_args(cli_args)

    def create_parser(self):
        """Do first round of parsing parameters to set options"""
        class ArgumentParser(argparse.ArgumentParser):
            """ Override Argument Parser so we can control the exit code"""
            def error(self, message):
                self.print_help(sys.stderr)
                self.exit(32, '%s: error: %s\n' % (self.prog, message))

        class ExtendAction(argparse.Action):
            """Support argument types that are lists and can be specified multiple times."""
            def __call__(self, parser, namespace, values, option_string=None):
                items = getattr(namespace, self.dest)
                items = [] if items is None else items
                for value in values:
                    if isinstance(value, list):
                        items.extend(value)
                    else:
                        items.append(value)
                setattr(namespace, self.dest, items)

        usage = (
            '\nBasic: cfn-lint test.yaml\n'
            'Ignore a rule: cfn-lint -I E3012 -- test.yaml\n'
            'Configure a rule: cfn-lint -x E3012:strict=false -t test.yaml\n'
            'Lint all yaml files in a folder: cfn-lint dir/**/*.yaml'
        )

        parser = ArgumentParser(
            description='CloudFormation Linter',
            usage=usage)
        parser.register('action', 'extend', ExtendAction)

        standard = parser.add_argument_group('Standard')
        advanced = parser.add_argument_group('Advanced / Debugging')

        # Alllow the template to be passes as an optional or a positional argument
        standard.add_argument(
            'templates', metavar='TEMPLATE', nargs='*', help='The CloudFormation template to be linted')
        standard.add_argument(
            '-t', '--template', metavar='TEMPLATE', dest='template_alt',
            help='The CloudFormation template to be linted', nargs='+', default=[], action='extend')
        standard.add_argument(
            '-b', '--ignore-bad-template', help='Ignore failures with Bad template',
            action='store_true'
        )
        standard.add_argument(
            '--ignore-templates', dest='ignore_templates',
            help='Ignore templates', nargs='+', default=[], action='extend'
        )
        advanced.add_argument(
            '-D', '--debug', help='Enable debug logging', action='store_true'
        )
        advanced.add_argument(
            '-I', '--info', help='Enable information logging', action='store_true'
        )
        standard.add_argument(
            '-f', '--format', help='Output Format', choices=['quiet', 'parseable', 'json']
        )

        standard.add_argument(
            '-l', '--list-rules', dest='listrules', default=False,
            action='store_true', help='list all the rules'
        )
        standard.add_argument(
            '-r', '--regions', dest='regions', nargs='+', default=[],
            type=comma_separated_arg, action='extend',
            help='list the regions to validate against.'
        )
        advanced.add_argument(
            '-a', '--append-rules', dest='append_rules', nargs='+', default=[],
            type=comma_separated_arg, action='extend',
            help='specify one or more rules directories using '
                 'one or more --append-rules arguments. '
        )
        standard.add_argument(
            '-i', '--ignore-checks', dest='ignore_checks', nargs='+', default=[],
            type=comma_separated_arg, action='extend',
            help='only check rules whose id do not match these values'
        )
        standard.add_argument(
            '-c', '--include-checks', dest='include_checks', nargs='+', default=[],
            type=comma_separated_arg, action='extend',
            help='include rules whose id match these values'
        )
        standard.add_argument(
            '-e', '--include-experimental', help='Include experimental rules', action='store_true'
        )

        standard.add_argument(
            '-x', '--configure-rule', dest='configure_rules', nargs='+', default={},
            action=RuleConfigurationAction,
            help='Provide configuration for a rule. Format RuleId:key=value. Example: E3012:strict=false'
        )

        advanced.add_argument(
            '-o', '--override-spec', dest='override_spec',
            help='A CloudFormation Spec override file that allows customization'
        )

        standard.add_argument(
            '-v', '--version', help='Version of cfn-lint', action='version',
            version='%(prog)s {version}'.format(version=__version__)
        )
        advanced.add_argument(
            '-u', '--update-specs', help='Update the CloudFormation Specs',
            action='store_true'
        )
        advanced.add_argument(
            '--update-documentation', help=argparse.SUPPRESS,
            action='store_true'
        )
        advanced.add_argument(
            '--update-iam-policies', help=argparse.SUPPRESS,
            action='store_true'
        )

        return parser


class TemplateArgs(object):
    """ Per Template Args """
    def __init__(self, template_args):
        self.set_template_args(template_args)

    def get_template_args(self):
        """ Get Template Args"""
        return self._template_args

    def set_template_args(self, template):
        """ Set Template Args"""
        defaults = {}
        if isinstance(template, dict):
            configs = template.get('Metadata', {}).get('cfn-lint', {}).get('config', {})

            if isinstance(configs, dict):
                for config_name, config_value in configs.items():
                    if config_name == 'ignore_checks':
                        if isinstance(config_value, list):
                            defaults['ignore_checks'] = config_value
                    if config_name == 'regions':
                        if isinstance(config_value, list):
                            defaults['regions'] = config_value
                    if config_name == 'append_rules':
                        if isinstance(config_value, list):
                            defaults['append_rules'] = config_value
                    if config_name == 'override_spec':
                        if isinstance(config_value, (six.string_types)):
                            defaults['override_spec'] = config_value
                    if config_name == 'ignore_bad_template':
                        if isinstance(config_value, bool):
                            defaults['ignore_bad_template'] = config_value
                    if config_name == 'include_checks':
                        if isinstance(config_value, list):
                            defaults['include_checks'] = config_value
                    if config_name == 'configure_rules':
                        if isinstance(config_value, dict):
                            defaults['configure_rules'] = config_value

        self._template_args = defaults

    template_args = property(get_template_args, set_template_args)


class ConfigMixIn(TemplateArgs, CliArgs, ConfigFileArgs, object):
    """ Mixin for the Configs """

    def __init__(self, cli_args):
        CliArgs.__init__(self, cli_args)
        # configure debug as soon as we can
        configure_logging(self.cli_args.debug, self.cli_args.info)
        ConfigFileArgs.__init__(self)
        TemplateArgs.__init__(self, {})

    def _get_argument_value(self, arg_name, is_template, is_config_file):
        """ Get Argument value """
        cli_value = getattr(self.cli_args, arg_name)
        template_value = self.template_args.get(arg_name)
        file_value = self.file_args.get(arg_name)
        if cli_value:
            return cli_value
        if template_value and is_template:
            return template_value
        if file_value and is_config_file:
            return file_value
        return cli_value

    @property
    def ignore_checks(self):
        """ ignore_checks """
        return self._get_argument_value('ignore_checks', True, True)

    @property
    def include_checks(self):
        """ include_checks """
        return self._get_argument_value('include_checks', True, True)

    @property
    def include_experimental(self):
        """ include_experimental """
        return self._get_argument_value('include_experimental', True, True)

    @property
    def regions(self):
        """ regions """
        results = self._get_argument_value('regions', True, True)
        if not results:
            return ['us-east-1']
        return results

    @property
    def ignore_bad_template(self):
        """ ignore_bad_template """
        return self._get_argument_value('ignore_bad_template', True, True)

    @property
    def debug(self):
        """ debug """
        return self._get_argument_value('debug', False, False)

    @property
    def format(self):
        """ format """
        return self._get_argument_value('format', False, True)

    @property
    def templates(self):
        """ templates """
        templates_args = self._get_argument_value('templates', False, True)
        template_alt_args = self._get_argument_value('template_alt', False, False)
        if template_alt_args:
            filenames = template_alt_args
        elif templates_args:
            filenames = templates_args
        else:
            return None

        # if only one is specified convert it to array
        if isinstance(filenames, six.string_types):
            filenames = [filenames]

        # handle different shells and Config files
        # some shells don't expand * and configparser won't expand wildcards
        all_filenames = []
        ignore_templates = self._ignore_templates()
        for filename in filenames:
            if sys.version_info >= (3, 5):
                # pylint: disable=E1123
                add_filenames = glob.glob(filename, recursive=True)
            else:
                add_filenames = glob.glob(filename)
            # only way to know of the glob failed is to test it
            # then add the filename as requested
            if not add_filenames:
                if filename not in ignore_templates:
                    all_filenames.append(filename)
            else:
                for add_filename in add_filenames:
                    if add_filename not in ignore_templates:
                        all_filenames.append(add_filename)

        return sorted(all_filenames)

    def _ignore_templates(self):
        """ templates """
        ignore_template_args = self._get_argument_value('ignore_templates', False, True)
        if ignore_template_args:
            filenames = ignore_template_args
        else:
            return []

        # if only one is specified convert it to array
        if isinstance(filenames, six.string_types):
            filenames = [filenames]

        # handle different shells and Config files
        # some shells don't expand * and configparser won't expand wildcards
        all_filenames = []
        for filename in filenames:
            if sys.version_info >= (3, 5):
                # pylint: disable=E1123
                add_filenames = glob.glob(filename, recursive=True)
            else:
                add_filenames = glob.glob(filename)
            # only way to know of the glob failed is to test it
            # then add the filename as requested
            if not add_filenames:
                all_filenames.append(filename)
            else:
                all_filenames.extend(add_filenames)

        return all_filenames

    @property
    def append_rules(self):
        """ append_rules """
        return self._get_argument_value('append_rules', False, True)

    @property
    def override_spec(self):
        """ override_spec """
        return self._get_argument_value('override_spec', False, True)

    @property
    def update_specs(self):
        """ update_specs """
        return self._get_argument_value('update_specs', False, False)

    @property
    def update_documentation(self):
        """ update_specs """
        return self._get_argument_value('update_documentation', False, False)

    @property
    def update_iam_policies(self):
        """ update_iam_policies """
        return self._get_argument_value('update_iam_policies', False, False)

    @property
    def listrules(self):
        """ listrules """
        return self._get_argument_value('listrules', False, False)

    @property
    def configure_rules(self):
        """ Configure rules """
        return self._get_argument_value('configure_rules', True, True)

"""
A basic plugin for performing calculations in ``LAMMPS`` using aiida.

The plugin will take the input parameters validate them against a schema
and then use them to generate the ``LAMMPS`` input file. The input file
is generated depending on the parameters provided, the type of potential,
the input structure and whether or not a restart file is provided.
"""
import os

from aiida import orm
from aiida.common import datastructures, exceptions
from aiida.engine import CalcJob

from aiida_lammps.common.generate_structure import generate_lammps_structure
from aiida_lammps.common.input_generator import generate_input_file
from aiida_lammps.data.lammps_potential import LammpsPotentialData
from aiida_lammps.data.trajectory import LammpsTrajectory


class BaseLammpsCalculation(CalcJob):
    """
    A basic plugin for performing calculations in ``LAMMPS`` using aiida.

    The plugin will take the input parameters validate them against a schema
    and then use them to generate the ``LAMMPS`` input file. The input file
    is generated depending on the parameters provided, the type of potential,
    the input structure and whether or not a restart file is provided.
    """

    _INPUT_FILENAME = "input.in"
    _STRUCTURE_FILENAME = "structure.dat"

    _DEFAULT_LOGFILE_FILENAME = "log.lammps"
    _DEFAULT_OUTPUT_FILENAME = "lammps_output"
    _DEFAULT_TRAJECTORY_FILENAME = "aiida_lammps.trajectory.dump"
    _DEFAULT_VARIABLES_FILENAME = "aiida_lammps.yaml"
    _DEFAULT_RESTART_FILENAME = "lammps.restart"
    _DEFAULT_POTENTIAL_FILENAME = "potential.dat"
    _DEFAULT_READ_RESTART_FILENAME = "aiida_lammps.restart"

    _DEFAULT_PARSER = "lammps.base"

    # In restarts, will not copy but use symlinks
    _default_symlink_usage = True

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input(
            "script",
            valid_type=orm.SinglefileData,
            required=False,
            help="Complete input script to use. If specified, `structure`, `potential` and `parameters` are ignored.",
        )
        spec.input(
            "structure",
            valid_type=orm.StructureData,
            required=False,
            help="Structure used in the ``LAMMPS`` calculation",
        )
        spec.input(
            "potential",
            valid_type=LammpsPotentialData,
            required=False,
            help="Potential used in the ``LAMMPS`` calculation",
        )
        spec.input(
            "parameters",
            valid_type=orm.Dict,
            required=False,
            help="Parameters that control the input script generated for the ``LAMMPS`` calculation",
        )
        spec.input(
            "settings",
            valid_type=orm.Dict,
            required=False,
            help="Additional settings that control the ``LAMMPS`` calculation",
        )
        spec.input(
            "input_restartfile",
            valid_type=orm.SinglefileData,
            required=False,
            help="Input restartfile to continue from a previous ``LAMMPS`` calculation",
        )
        spec.input(
            "parent_folder",
            valid_type=orm.RemoteData,
            required=False,
            help="An optional working directory of a previously completed calculation to restart from.",
        )
        spec.input(
            "metadata.options.input_filename",
            valid_type=str,
            default=cls._INPUT_FILENAME,
        )
        spec.input(
            "metadata.options.structure_filename",
            valid_type=str,
            default=cls._STRUCTURE_FILENAME,
        )
        spec.input(
            "metadata.options.output_filename",
            valid_type=str,
            default=cls._DEFAULT_OUTPUT_FILENAME,
        )
        spec.input(
            "metadata.options.logfile_filename",
            valid_type=str,
            default=cls._DEFAULT_LOGFILE_FILENAME,
        )
        spec.input(
            "metadata.options.variables_filename",
            valid_type=str,
            default=cls._DEFAULT_VARIABLES_FILENAME,
        )
        spec.input(
            "metadata.options.trajectory_filename",
            valid_type=str,
            default=cls._DEFAULT_TRAJECTORY_FILENAME,
        )
        spec.input(
            "metadata.options.restart_filename",
            valid_type=str,
            default=cls._DEFAULT_RESTART_FILENAME,
        )
        spec.inputs["metadata"]["options"]["parser_name"].default = cls._DEFAULT_PARSER
        spec.inputs.validator = cls.validate_inputs

        spec.output(
            "results",
            valid_type=orm.Dict,
            required=True,
            help="The data extracted from the lammps log file",
        )
        spec.output(
            "trajectories",
            valid_type=LammpsTrajectory,
            required=True,
            help="The data extracted from the lammps trajectory file",
        )
        spec.output(
            "time_dependent_computes",
            valid_type=orm.ArrayData,
            required=True,
            help="The data with the time dependent computes parsed from the lammps.log",
        )
        spec.output(
            "restartfile",
            valid_type=orm.SinglefileData,
            required=False,
            help="The restartfile of a ``LAMMPS`` calculation",
        )
        spec.output(
            "structure",
            valid_type=orm.StructureData,
            required=False,
            help="The output structure.",
        )
        spec.exit_code(
            350,
            "ERROR_NO_RETRIEVED_FOLDER",
            message="the retrieved folder data node could not be accessed.",
            invalidates_cache=True,
        )
        spec.exit_code(
            351,
            "ERROR_LOG_FILE_MISSING",
            message="the file with the lammps log was not found",
            invalidates_cache=True,
        )
        spec.exit_code(
            352,
            "ERROR_FINAL_VARIABLE_FILE_MISSING",
            message="the file with the final variables was not found",
            invalidates_cache=True,
        )
        spec.exit_code(
            353,
            "ERROR_TRAJECTORY_FILE_MISSING",
            message="the file with the trajectories was not found",
            invalidates_cache=True,
        )
        spec.exit_code(
            354,
            "ERROR_STDOUT_FILE_MISSING",
            message="the stdout output file was not found",
        )
        spec.exit_code(
            355,
            "ERROR_STDERR_FILE_MISSING",
            message="the stderr output file was not found",
        )
        spec.exit_code(
            356,
            "ERROR_RESTART_FILE_MISSING",
            message="the file with the restart information was not found",
        )
        spec.exit_code(
            357,
            "ERROR_CALCULATION_DID_NOT_FINISH",
            message="The calculation did not finish properly but an intermediate restartfile was found",
        )
        spec.exit_code(
            1001,
            "ERROR_PARSING_LOGFILE",
            message="error parsing the log file has failed.",
        )
        spec.exit_code(
            1002,
            "ERROR_PARSING_FINAL_VARIABLES",
            message="error parsing the final variable file has failed.",
        )

    @classmethod
    def validate_inputs(cls, value, ctx):
        """Validate the top-level inputs namespace."""
        if "script" not in value and any(
            key not in value for key in ("structure", "potential", "parameters")
        ):
            return (
                "Unless `script` is specified the inputs `structure`, `potential` and "
                "`parameters` have to be specified."
            )

    def prepare_for_submission(self, folder):
        """
        Create the input files from the input nodes passed to this instance of the `CalcJob`.
        """
        # pylint: disable=too-many-locals

        # Get the name of the trajectory file
        _trajectory_filename = self.inputs.metadata.options.trajectory_filename

        # Get the name of the variables file
        _variables_filename = self.inputs.metadata.options.variables_filename

        # Get the name of the restart file
        _restart_filename = self.inputs.metadata.options.restart_filename

        # Get the name of the output file
        _output_filename = self.inputs.metadata.options.output_filename

        # Get the name of the logfile file
        _logfile_filename = self.inputs.metadata.options.logfile_filename

        # Get the parameters dictionary so that they can be used for creating
        # the input file
        if "parameters" in self.inputs:
            _parameters = self.inputs.parameters.get_dict()
        else:
            _parameters = {}

        if "settings" in self.inputs:
            settings = self.inputs.settings.get_dict()
        else:
            settings = {}

        # Set the remote copy list and the symlink so that if one needs to use restartfiles from
        # a previous calculations one can do so without problems
        remote_copy_list = []
        remote_symlink_list = []
        local_copy_list = []
        retrieve_temporary_list = []
        retrieve_list = [
            _output_filename,
            _logfile_filename,
            _variables_filename,
            _trajectory_filename,
        ]

        calcinfo = datastructures.CalcInfo()

        # Handle the restart file for simulations coming from previous runs
        restart_data = self.handle_restartfiles(
            settings=settings, parameters=_parameters,
        )
        _read_restart_filename = restart_data.get("restart_file", None)
        remote_copy_list += restart_data.get("remote_copy_list", [])
        remote_symlink_list += restart_data.get("remote_symlink_list", [])
        local_copy_list += restart_data.get("local_copy_list", [])
        retrieve_list += restart_data.get("retrieve_list", [])
        retrieve_temporary_list += restart_data.get("retrieve_temporary_list", [])

        if "script" in self.inputs:
            input_filecontent = self.inputs.script.get_content()
        else:

            # Generate the content of the structure file based on the input
            # structure
            structure_filecontent, _ = generate_lammps_structure(
                self.inputs.structure,
                self.inputs.potential.atom_style,
            )

            # Get the name of the structure file and write it to the remote folder
            _structure_filename = self.inputs.metadata.options.structure_filename

            with folder.open(_structure_filename, "w") as handle:
                handle.write(structure_filecontent)

            # Write the potential to the remote folder
            with folder.open(self._DEFAULT_POTENTIAL_FILENAME, "w") as handle:
                handle.write(self.inputs.potential.get_content())

            # Write the input file content. This function will also check the
            # sanity of the passed paremters when comparing it to a schema
            input_filecontent = generate_input_file(
                potential=self.inputs.potential,
                structure=self.inputs.structure,
                parameters=_parameters,
                restart_filename=_restart_filename,
                trajectory_filename=_trajectory_filename,
                variables_filename=_variables_filename,
                read_restart_filename=_read_restart_filename,
            )

        # Get the name of the input file, and write it to the remote folder
        _input_filename = self.inputs.metadata.options.input_filename

        with folder.open(_input_filename, "w") as handle:
            handle.write(input_filecontent)

        codeinfo = datastructures.CodeInfo()
        # Command line variables to ensure that the input file from LAMMPS can
        # be read
        codeinfo.cmdline_params = ["-in", _input_filename, "-log", _logfile_filename]
        # Set the code uuid
        codeinfo.code_uuid = self.inputs.code.uuid
        # Set the name of the stdout
        codeinfo.stdout_name = _output_filename

        # Generate the datastructure for the calculation information
        calcinfo.uuid = str(self.uuid)

        calcinfo.local_copy_list = local_copy_list
        calcinfo.remote_copy_list = remote_copy_list
        calcinfo.remote_symlink_list = remote_symlink_list
        # Define the list of temporary files that will be retrieved
        calcinfo.retrieve_temporary_list = retrieve_temporary_list
        # Set the files that must be retrieved
        calcinfo.retrieve_list = retrieve_list
        # Set the information of the code into the calculation datastructure
        calcinfo.codes_info = [codeinfo]

        return calcinfo

    def handle_restartfiles(
        self,
        settings: dict,
        parameters: dict,
    ) -> dict:
        """Get the information needed to handle the restartfiles

        :param settings: Additional settings that control the ``LAMMPS`` calculation
        :type settings: dict
        :param parameters: Parameters that control the input script generated for the ``LAMMPS`` calculation
        :type parameters: dict
        :raises exceptions.InputValidationError: if the name of the given restart file is not in the remote folder
        :return: dictionary with the information about how to handle the restartfile either for parsing, \
            storage or input
        :rtype: dict
        """
        local_copy_list = []
        remote_symlink_list = []
        remote_copy_list = []
        retrieve_list = []
        retrieve_temporary_list = []
        # If there is a restartfile set its name to the input variables and
        # write it in the remote folder
        if "input_restartfile" in self.inputs:
            _read_restart_filename = self._DEFAULT_READ_RESTART_FILENAME
            local_copy_list.append(
                (
                    self.inputs.input_restartfile.uuid,
                    self.inputs.input_restartfile.filename,
                    self._DEFAULT_READ_RESTART_FILENAME,
                )
            )
        else:
            _read_restart_filename = None

        # check if there is a parent folder to restart the simulation from a previous run
        if "parent_folder" in self.inputs:
            # Check if one should do symlinks or if one should copy the files
            # By default symlinks are used as the file can be quite large
            symlink = settings.pop("parent_folder_symlink", self._default_symlink_usage)
            # Find the name of the previous restartfile, if none is given the default one is assumed
            # Setting the name here will mean that if the input file is generated from the parameters
            # that this name will be used
            _read_restart_filename = settings.pop(
                "previous_restartfile", self._DEFAULT_RESTART_FILENAME
            )

            if not _read_restart_filename in self.inputs.parent_folder.listdir():
                raise exceptions.InputValidationError(
                    f'The name "{_read_restart_filename}" for the restartfile is not present in the '
                    f'remote folder "{self.input.parent_folder.uuid}"'
                )

            if symlink:
                # Symlink the old restart file to the new one in the current directoy
                remote_symlink_list.append(
                    (
                        self.inputs.parent_folder.computer.uuid,
                        os.path.join(
                            self.inputs.parent_folder.get_remote_path(),
                            _read_restart_filename,
                        ),
                        'input_lammps.restart',
                    )
                )
                _read_restart_filename = 'input_lammps.restart'
            else:
                # Copy the old restart file to the current directory
                remote_copy_list.append(
                    (
                        self.inputs.parent_folder.computer.uuid,
                        os.path.join(
                            self.inputs.parent_folder.get_remote_path(),
                            _read_restart_filename,
                        ),
                        'input_lammps.restart',
                    )
                )
                _read_restart_filename = 'input_lammps.restart'

        # Add the restart file to the list of files to be retrieved if we want to store it in the database
        if "restart" in parameters and settings.get("store_restart", False):
            if parameters.get("restart", {}).get("print_final", False):
                retrieve_list.append(self.inputs.metadata.options.restart_filename)
            if parameters.get("restart", {}).get("print_intermediate", False):
                retrieve_temporary_list.append(
                    (f"{self.inputs.metadata.options.restart_filename}*", ".", None)
                )

        data = {
            "remote_copy_list": remote_copy_list,
            "remote_symlink_list": remote_symlink_list,
            "local_copy_list": local_copy_list,
            "restart_file": _read_restart_filename,
            "retrieve_list": retrieve_list,
            "retrieve_temporary_list": retrieve_temporary_list,
        }
        return data

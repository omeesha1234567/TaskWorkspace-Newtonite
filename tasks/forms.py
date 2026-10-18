import uuid
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Team, TeamMembership, TeamRole, Task, TaskStatus, TaskPriority
from .permissions import get_accessible_teams_qs


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter your username',
            'autocomplete': 'username',
            'required': True,
            'id': 'login-username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'required': True,
            'id': 'login-password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox', 'id': 'login-remember'})
    )


class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Minimum 8 characters',
            'autocomplete': 'new-password',
            'required': True,
            'id': 'reg-password'
        })
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Repeat your password',
            'autocomplete': 'new-password',
            'required': True,
            'id': 'reg-confirm-password'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'johndoe', 'required': True}),
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'John', 'required': True}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Doe', 'required': True}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'john@example.com', 'required': True}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("A user with that username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
            if len(password) < 8:
                self.add_error('password', "Password must be at least 8 characters long.")
        return cleaned_data


class TaskCreateForm(forms.ModelForm):
    idempotency_key = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )

    class Meta:
        model = Task
        fields = ['title', 'description', 'team', 'priority', 'status', 'assignee', 'due_date']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Implement OAuth2 login flow', 'required': True}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 4, 'placeholder': 'Details and acceptance criteria...'}),
            'team': forms.Select(attrs={'class': 'form-select', 'id': 'task-team-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'assignee': forms.Select(attrs={'class': 'form-select', 'id': 'task-assignee-select'}),
            'due_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        }

    def __init__(self, *args, user=None, initial_team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get('idempotency_key'):
            self.initial['idempotency_key'] = str(uuid.uuid4())

        # Restrict status choices: initial status cannot be RESOLVED
        self.fields['status'].choices = [
            (TaskStatus.OPEN, 'Open'),
            (TaskStatus.IN_PROGRESS, 'In Progress')
        ]

        if user:
            accessible_teams = get_accessible_teams_qs(user)
            self.fields['team'].queryset = accessible_teams

            selected_team = None
            # 1. Check submitted form data first (POST)
            if self.data and self.data.get('team'):
                try:
                    submitted_team_id = int(self.data.get('team'))
                    selected_team = accessible_teams.filter(pk=submitted_team_id).first()
                except (ValueError, TypeError):
                    selected_team = None

            # 2. Check explicitly provided initial_team
            if not selected_team and initial_team and initial_team in accessible_teams:
                selected_team = initial_team

            # 3. Default to user's first accessible team
            if not selected_team and accessible_teams.exists():
                selected_team = accessible_teams.first()

            if selected_team:
                self.initial['team'] = selected_team
                # Restrict assignee choices to active members of the selected team
                self.fields['assignee'].queryset = User.objects.filter(
                    team_memberships__team=selected_team
                ).distinct()
            else:
                self.fields['assignee'].queryset = User.objects.none()

        self.fields['assignee'].required = False
        self.fields['assignee'].empty_label = "Unassigned"

    def clean(self):
        cleaned_data = super().clean()
        team = cleaned_data.get('team')
        assignee = cleaned_data.get('assignee')
        if team and assignee:
            if not TeamMembership.objects.filter(team=team, user=assignee).exists():
                self.add_error('assignee', f"The selected user '{assignee.username}' is not a member of team '{team.name}'.")
        return cleaned_data


class TaskEditForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput(), required=True)

    class Meta:
        model = Task
        fields = ['title', 'description', 'priority', 'status', 'assignee', 'due_date', 'version']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'required': True}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 5}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'assignee': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Restrict assignees to current task's team members
            self.fields['assignee'].queryset = User.objects.filter(
                team_memberships__team=self.instance.team
            ).distinct()
            self.fields['assignee'].required = False
            self.fields['assignee'].empty_label = "Unassigned"
            self.initial['version'] = self.instance.version

    def clean(self):
        cleaned_data = super().clean()
        assignee = cleaned_data.get('assignee')
        if self.instance and self.instance.team and assignee:
            if not TeamMembership.objects.filter(team=self.instance.team, user=assignee).exists():
                self.add_error('assignee', f"The selected user '{assignee.username}' is not a member of team '{self.instance.team.name}'.")
        return cleaned_data


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Backend Platform Team', 'required': True}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 3, 'placeholder': 'Mandate and scope of this team'}),
        }


class AddTeamMemberForm(forms.Form):
    username_or_email = forms.CharField(
        label="Username or Email",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter member username or email',
            'required': True,
            'id': 'add-member-input'
        })
    )
    role = forms.ChoiceField(
        choices=TeamRole.choices,
        initial=TeamRole.MEMBER,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'add-member-role'})
    )

    def clean_username_or_email(self):
        val = self.cleaned_data['username_or_email'].strip()
        user = User.objects.filter(username__iexact=val).first() or User.objects.filter(email__iexact=val).first()
        if not user:
            raise ValidationError(f"No user found matching '{val}'. Please check spelling.")
        return user


class ChangeMemberRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=TeamRole.choices,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class TaskAttachmentForm(forms.Form):
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={'class': 'form-input-file', 'id': 'task-file-upload-input', 'required': True})
    )


class WorkspaceInvitationForm(forms.Form):
    email = forms.EmailField(
        label="Invitee Email Address",
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
            'placeholder': 'colleague@company.com',
            'required': True,
            'id': 'invite-email-input'
        })
    )
    role = forms.ChoiceField(
        choices=TeamRole.choices,
        initial=TeamRole.MEMBER,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'invite-role-select'})
    )


class SharedDocumentUploadForm(forms.Form):
    file = forms.FileField(
        label="Select Document",
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-input-file',
            'id': 'shared-doc-file-input',
            'required': True
        })
    )
    task = forms.ModelChoiceField(
        queryset=Task.objects.none(),
        required=False,
        empty_label="— General Team Library (No Task) —",
        label="Associate with Task (Optional)",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'shared-doc-task-select'
        })
    )
    description = forms.CharField(
        required=False,
        label="Description / Short Note",
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 2,
            'placeholder': 'Optional brief notes regarding this document or revision...',
            'id': 'shared-doc-desc-input'
        })
    )

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team:
            self.fields['task'].queryset = Task.objects.filter(team=team, is_archived=False).order_by('-created_at')

